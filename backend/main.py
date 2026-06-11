from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from .connection_test import test_connection
from .models import payload_from_dict
from .remote.mcp_audit import append_mcp_failed, append_mcp_finished, append_mcp_started
from .remote.mcp_tools import get_mcp_tools
from .remote.service import RemoteApplicationService
from .ssh_config_service import create_entry, delete_entry, get_entry, list_entries, update_entry


HOST = "127.0.0.1"
PORT = 8777
REMOTE_SERVICE = RemoteApplicationService()


def _json_bytes(data: object) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


class SSHConfigHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: int, data: object) -> None:
        body = _json_bytes(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def do_OPTIONS(self) -> None:
        self._send(HTTPStatus.NO_CONTENT, {})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path == "/api/health":
                self._send(HTTPStatus.OK, {"success": True, "message": "ok"})
                return
            if path == "/api/ssh-configs":
                self._send(HTTPStatus.OK, [entry.model_dump() for entry in list_entries()])
                return
            if path.startswith("/api/ssh-configs/"):
                host = unquote(path.removeprefix("/api/ssh-configs/"))
                entry = get_entry(host)
                if entry is None:
                    self._send(HTTPStatus.NOT_FOUND, {"detail": f"Host '{host}' 未找到"})
                    return
                self._send(HTTPStatus.OK, entry.model_dump())
                return
            if path == "/api/remote/targets":
                self._send(HTTPStatus.OK, REMOTE_SERVICE.list_targets())
                return
            if path == "/api/remote/capabilities":
                self._send(HTTPStatus.OK, REMOTE_SERVICE.capabilities())
                return
            if path == "/api/remote/plans":
                self._send(
                    HTTPStatus.OK,
                    REMOTE_SERVICE.list_plans(
                        target_alias=_query_one(query, "target_alias"),
                        status=_query_one(query, "status"),
                        limit=_query_int(query, "limit", 50),
                    ),
                )
                return
            if path == "/api/remote/transfers":
                self._send(
                    HTTPStatus.OK,
                    REMOTE_SERVICE.list_transfers(
                        target_alias=_query_one(query, "target_alias"),
                        status=_query_one(query, "status"),
                        limit=_query_int(query, "limit", 20),
                    ),
                )
                return
            if path.startswith("/api/remote/transfers/"):
                transfer_id = unquote(path.removeprefix("/api/remote/transfers/"))
                self._send(
                    HTTPStatus.OK,
                    REMOTE_SERVICE.get_transfer(transfer_id=transfer_id),
                )
                return
            if path.startswith("/api/remote/plans/"):
                plan_id = unquote(path.removeprefix("/api/remote/plans/"))
                self._send(HTTPStatus.OK, REMOTE_SERVICE.get_plan(plan_id=plan_id))
                return
            if path == "/api/remote/audit-events":
                self._send(
                    HTTPStatus.OK,
                    REMOTE_SERVICE.list_audit_events(
                        target_alias=_query_one(query, "target_alias"),
                        plan_id=_query_one(query, "plan_id"),
                        run_id=_query_one(query, "run_id"),
                        event_type=_query_one(query, "event_type"),
                        limit=_query_int(query, "limit", 50),
                    ),
                )
                return
            self._send(HTTPStatus.NOT_FOUND, {"detail": "Not found"})
        except KeyError as exc:
            self._send(HTTPStatus.NOT_FOUND, {"detail": str(exc).strip("'")})
        except ValueError as exc:
            self._send(HTTPStatus.BAD_REQUEST, {"detail": str(exc)})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/ssh-configs":
                payload = payload_from_dict(self._read_json())
                entry = create_entry(payload)
                self._send(HTTPStatus.CREATED, entry.model_dump())
                return
            if path == "/api/ssh-configs/test":
                payload = payload_from_dict(self._read_json())
                message = test_connection(payload)
                self._send(HTTPStatus.OK, {"success": True, "message": message})
                return
            if path == "/api/remote/preview-instruction":
                payload = self._read_json()
                self._send(
                    HTTPStatus.OK,
                    REMOTE_SERVICE.preview_instruction(
                        target_alias=str(payload.get("target_alias", "")),
                        instruction_data=_dict_arg(payload.get("instruction")),
                    ),
                )
                return
            if path == "/api/remote/plans":
                payload = self._read_json()
                self._send(
                    HTTPStatus.CREATED,
                    REMOTE_SERVICE.create_plan(
                        target_alias=str(payload.get("target_alias", "")),
                        goal=str(payload.get("goal", "")),
                        instructions_data=_list_of_dicts(payload.get("instructions")),
                        created_by=str(payload.get("created_by", "web")),
                        ttl_seconds=int(payload.get("ttl_seconds", 86400)),
                    ),
                )
                return
            if path == "/api/remote/run-instruction":
                payload = self._read_json()
                self._send(
                    HTTPStatus.OK,
                    REMOTE_SERVICE.run_instruction(
                        target_alias=str(payload.get("target_alias", "")),
                        instruction_data=_dict_arg(payload.get("instruction")),
                        actor=str(payload.get("actor", "web")),
                    ),
                )
                return
            if path.endswith("/approve") and path.startswith("/api/remote/plans/"):
                plan_id = unquote(path.removeprefix("/api/remote/plans/").removesuffix("/approve"))
                payload = self._read_json()
                self._send(
                    HTTPStatus.OK,
                    REMOTE_SERVICE.approve_plan(
                        plan_id=plan_id,
                        plan_hash=_optional_str(payload.get("plan_hash")),
                        approved_by=str(payload.get("approved_by", "web")),
                        comment=_optional_str(payload.get("comment")),
                    ),
                )
                return
            if path.endswith("/reject") and path.startswith("/api/remote/plans/"):
                plan_id = unquote(path.removeprefix("/api/remote/plans/").removesuffix("/reject"))
                payload = self._read_json()
                self._send(
                    HTTPStatus.OK,
                    REMOTE_SERVICE.reject_plan(
                        plan_id=plan_id,
                        rejected_by=str(payload.get("rejected_by", "web")),
                        reason=_optional_str(payload.get("reason")),
                    ),
                )
                return
            if path.endswith("/execute") and path.startswith("/api/remote/plans/"):
                plan_id = unquote(path.removeprefix("/api/remote/plans/").removesuffix("/execute"))
                payload = self._read_json()
                self._send(
                    HTTPStatus.OK,
                    REMOTE_SERVICE.execute_plan(
                        plan_id=plan_id,
                        plan_hash=_optional_str(payload.get("plan_hash")),
                        actor=str(payload.get("actor", "web")),
                    ),
                )
                return
            if path == "/api/remote/transfers":
                payload = self._read_json()
                self._send(
                    HTTPStatus.OK,
                    REMOTE_SERVICE.start_transfer(
                        plan_id=str(payload.get("plan_id", "")),
                        plan_hash=_optional_str(payload.get("plan_hash")),
                        step_id=str(payload.get("step_id", "")),
                        actor=str(payload.get("actor", "web")),
                    ),
                )
                return
            if path.endswith("/cancel") and path.startswith("/api/remote/transfers/"):
                transfer_id = unquote(
                    path.removeprefix("/api/remote/transfers/").removesuffix("/cancel")
                )
                payload = self._read_json()
                self._send(
                    HTTPStatus.OK,
                    REMOTE_SERVICE.cancel_transfer(
                        transfer_id=transfer_id,
                        reason=_optional_str(payload.get("reason")),
                        actor=str(payload.get("actor", "web")),
                    ),
                )
                return
            if path == "/mcp":
                self._send(HTTPStatus.OK, _handle_mcp(self._read_json()))
                return
            self._send(HTTPStatus.NOT_FOUND, {"detail": "Not found"})
        except KeyError as exc:
            self._send(HTTPStatus.NOT_FOUND, {"detail": str(exc).strip("'")})
        except ValueError as exc:
            status = HTTPStatus.CONFLICT if "已存在" in str(exc) else HTTPStatus.BAD_REQUEST
            self._send(status, {"detail": str(exc)})
        except RuntimeError as exc:
            self._send(HTTPStatus.BAD_REQUEST, {"detail": f"连接测试失败：{exc}"})

    def do_PUT(self) -> None:
        path = urlparse(self.path).path
        if not path.startswith("/api/ssh-configs/"):
            self._send(HTTPStatus.NOT_FOUND, {"detail": "Not found"})
            return
        host = unquote(path.removeprefix("/api/ssh-configs/"))
        try:
            payload = payload_from_dict(self._read_json())
            entry = update_entry(host, payload)
            self._send(HTTPStatus.OK, entry.model_dump())
        except KeyError as exc:
            self._send(HTTPStatus.NOT_FOUND, {"detail": str(exc).strip("'")})
        except ValueError as exc:
            status = HTTPStatus.CONFLICT if "已存在" in str(exc) else HTTPStatus.BAD_REQUEST
            self._send(status, {"detail": str(exc)})

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if not path.startswith("/api/ssh-configs/"):
            self._send(HTTPStatus.NOT_FOUND, {"detail": "Not found"})
            return
        host = unquote(path.removeprefix("/api/ssh-configs/"))
        try:
            delete_entry(host)
            self._send(HTTPStatus.OK, {"success": True, "message": f"已删除 Host {host}"})
        except KeyError as exc:
            self._send(HTTPStatus.NOT_FOUND, {"detail": str(exc).strip("'")})


def _handle_mcp(request: dict[str, object]) -> dict[str, object]:
    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        params = _dict_arg(request.get("params"))
        protocol_version = str(params.get("protocolVersion") or "2025-06-18")
        return _mcp_result(
            request_id,
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "remote-ssh-mcp", "version": "0.1.0"},
            },
        )
    if method == "ping":
        return _mcp_result(request_id, {})
    if method == "tools/list":
        return _mcp_result(request_id, {"tools": get_mcp_tools()})
    if method != "tools/call":
        return _mcp_error(request_id, -32601, f"Method not found: {method}")

    name = ""
    started = None
    try:
        params = _dict_arg(request.get("params"))
        name = str(params.get("name", ""))
        args = _dict_arg(params.get("arguments", {}))
        started = append_mcp_started(
            REMOTE_SERVICE.audit_store,
            request_id=request_id,
            tool_name=name,
            arguments=args,
        )
        result = _dispatch_tool(name, args)
        append_mcp_finished(
            REMOTE_SERVICE.audit_store,
            request_id=request_id,
            tool_name=name,
            result=result,
            started=started,
        )
        text = json.dumps(result, ensure_ascii=False, indent=2)
        return _mcp_result(
            request_id,
            {"content": [{"type": "text", "text": text}]},
        )
    except Exception as exc:
        if started is not None:
            append_mcp_failed(
                REMOTE_SERVICE.audit_store,
                request_id=request_id,
                tool_name=name,
                error=exc,
                started=started,
            )
        return _mcp_error(request_id, -32000, str(exc))


def _mcp_result(request_id: object, result: dict[str, object]) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _mcp_error(request_id: object, code: int, message: str) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _dispatch_tool(name: str, args: dict[str, object]) -> dict[str, object]:
    if name in {"remote_list_targets"}:
        return REMOTE_SERVICE.list_targets()
    if name in {"remote_get_capabilities"}:
        return REMOTE_SERVICE.capabilities()
    if name in {"remote_preview_instruction"}:
        return REMOTE_SERVICE.preview_instruction(
            target_alias=str(args.get("target_alias", "")),
            instruction_data=_dict_arg(args.get("instruction")),
        )
    if name in {"remote_create_plan"}:
        return REMOTE_SERVICE.create_plan(
            target_alias=str(args.get("target_alias", "")),
            goal=str(args.get("goal", "")),
            instructions_data=_list_of_dicts(args.get("instructions")),
            created_by=str(args.get("created_by", "mcp-client")),
        )
    if name in {"remote_list_plans", "ssh_list_plans"}:
        return REMOTE_SERVICE.list_plans(
            target_alias=_optional_str(args.get("target_alias")),
            status=_optional_str(args.get("status")),
            limit=int(args.get("limit", 50)),
        )
    if name in {"remote_get_plan", "ssh_get_plan"}:
        return REMOTE_SERVICE.get_plan(plan_id=str(args.get("plan_id", "")))
    if name in {"remote_approve_plan", "ssh_approve_plan"}:
        return REMOTE_SERVICE.approve_plan(
            plan_id=str(args.get("plan_id", "")),
            plan_hash=_optional_str(args.get("plan_hash")),
            approved_by=str(args.get("approved_by", "mcp-client")),
            comment=_optional_str(args.get("comment", args.get("approval_note"))),
        )
    if name in {"remote_reject_plan", "ssh_reject_plan"}:
        return REMOTE_SERVICE.reject_plan(
            plan_id=str(args.get("plan_id", "")),
            rejected_by=str(args.get("rejected_by", "mcp-client")),
            reason=_optional_str(args.get("reason")),
        )
    if name in {"remote_execute_plan", "ssh_execute_plan"}:
        return REMOTE_SERVICE.execute_plan(
            plan_id=str(args.get("plan_id", "")),
            plan_hash=_optional_str(args.get("plan_hash")),
            actor=str(args.get("actor", "mcp-client")),
        )
    if name == "remote_start_transfer":
        return REMOTE_SERVICE.start_transfer(
            plan_id=str(args.get("plan_id", "")),
            plan_hash=_optional_str(args.get("plan_hash")),
            step_id=str(args.get("step_id", "")),
            actor=str(args.get("actor", "mcp-client")),
        )
    if name == "remote_get_transfer":
        return REMOTE_SERVICE.get_transfer(
            transfer_id=str(args.get("transfer_id", ""))
        )
    if name == "remote_cancel_transfer":
        return REMOTE_SERVICE.cancel_transfer(
            transfer_id=str(args.get("transfer_id", "")),
            reason=_optional_str(args.get("reason")),
            actor=str(args.get("actor", "mcp-client")),
        )
    if name == "remote_list_transfers":
        return REMOTE_SERVICE.list_transfers(
            target_alias=_optional_str(args.get("target_alias")),
            status=_optional_str(args.get("status")),
            limit=int(args.get("limit", 20)),
        )
    if name in {"remote_run_instruction"}:
        return REMOTE_SERVICE.run_instruction(
            target_alias=str(args.get("target_alias", "")),
            instruction_data=_dict_arg(args.get("instruction")),
            actor=str(args.get("actor", "mcp-client")),
        )
    if name in {"remote_list_audit_events", "ssh_read_audit_log"}:
        return REMOTE_SERVICE.list_audit_events(
            target_alias=_optional_str(args.get("target_alias")),
            plan_id=_optional_str(args.get("plan_id")),
            run_id=_optional_str(args.get("run_id")),
            event_type=_optional_str(args.get("event_type", args.get("event_filter"))),
            limit=int(args.get("limit", 50)),
        )
    raise ValueError(f"Unknown tool: {name}")


def _query_one(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def _query_int(query: dict[str, list[str]], key: str, default: int) -> int:
    value = _query_one(query, key)
    return int(value) if value else default


def _dict_arg(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("expected object")
    return value  # type: ignore[return-value]


def _list_of_dicts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("expected list")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError("expected list of objects")
    return value  # type: ignore[return-value]


def _optional_str(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def run(host: str = HOST, port: int = PORT) -> None:
    server = ThreadingHTTPServer((host, port), SSHConfigHandler)
    print(f"SSH Config Editor API listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
