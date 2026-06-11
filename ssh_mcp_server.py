#!/usr/bin/env python3
from __future__ import annotations

import atexit
import json
import sys
from typing import Any

from backend.remote.mcp_audit import append_mcp_failed, append_mcp_finished, append_mcp_started
from backend.remote.mcp_tools import get_mcp_tools
from backend.remote.service import RemoteApplicationService
from backend.ssh.pool import SSHConnectionPool


POOL = SSHConnectionPool()
SERVICE = RemoteApplicationService(pool=POOL)
atexit.register(POOL.shutdown)
WRITE_MODE = "headers"


def main() -> None:
    while True:
        request = _read_message()
        if request is None:
            return
        response = _handle_request(request)
        if response is not None:
            _write_message(response)


def _read_message() -> dict[str, Any] | None:
    global WRITE_MODE
    headers: dict[str, str] = {}
    while True:
        raw_line = sys.stdin.buffer.readline()
        if raw_line == b"":
            return None
        stripped = raw_line.strip()
        if stripped.startswith(b"{"):
            WRITE_MODE = "jsonl"
            text = stripped.decode("utf-8")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                decoder = json.JSONDecoder()
                obj, _ = decoder.raw_decode(text)
                return obj
        line = stripped.decode("utf-8")
        if not line:
            break
        name, _, value = line.partition(":")
        headers[name.lower()] = value.strip()

    length = int(headers.get("content-length", "0") or 0)
    if length <= 0:
        return None
    raw = sys.stdin.buffer.read(length)
    text = raw.decode("utf-8").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # tolerate trailing content after the first complete JSON object
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(text)
        return obj


def _write_message(message: dict[str, Any]) -> None:
    raw = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if WRITE_MODE == "jsonl":
        sys.stdout.buffer.write(raw + b"\n")
        sys.stdout.buffer.flush()
        return
    sys.stdout.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


def _handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")

    if method == "notifications/initialized":
        return None
    if method == "ping":
        return _result(request_id, {})
    if method == "initialize":
        params = _dict(request.get("params"))
        protocol_version = str(params.get("protocolVersion") or "2025-06-18")
        return _result(
            request_id,
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "remote-ssh-mcp", "version": "0.1.0"},
            },
        )
    if method == "tools/list":
        return _result(request_id, {"tools": get_mcp_tools()})
    if method == "tools/call":
        params = _dict(request.get("params"))
        name = str(params.get("name", ""))
        arguments = _dict(params.get("arguments", {}))
        started = append_mcp_started(
            SERVICE.audit_store,
            request_id=request_id,
            tool_name=name,
            arguments=arguments,
        )
        try:
            payload = _dispatch_tool(name, arguments)
            append_mcp_finished(
                SERVICE.audit_store,
                request_id=request_id,
                tool_name=name,
                result=payload,
                started=started,
            )
            return _result(
                request_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(payload, ensure_ascii=False, indent=2),
                        }
                    ],
                    "isError": not bool(payload.get("success", True)),
                },
            )
        except Exception as exc:
            append_mcp_failed(
                SERVICE.audit_store,
                request_id=request_id,
                tool_name=name,
                error=exc,
                started=started,
            )
            return _result(
                request_id,
                {
                    "content": [{"type": "text", "text": f"Error: {exc}"}],
                    "isError": True,
                },
            )
    if request_id is None:
        return None
    return _error(request_id, -32601, f"Method not found: {method}")


def _dispatch_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "remote_list_targets":
        return SERVICE.list_targets()
    if name == "remote_get_capabilities":
        return SERVICE.capabilities()
    if name == "remote_preview_instruction":
        return SERVICE.preview_instruction(
            target_alias=str(args.get("target_alias", "")),
            instruction_data=_dict(args.get("instruction")),
        )
    if name == "remote_create_plan":
        return SERVICE.create_plan(
            target_alias=str(args.get("target_alias", "")),
            goal=str(args.get("goal", "")),
            instructions_data=_list_of_dicts(args.get("instructions")),
            created_by=str(args.get("created_by", "mcp-client")),
            ttl_seconds=int(args.get("ttl_seconds", 86400)),
        )
    if name in {"remote_list_plans", "ssh_list_plans"}:
        return SERVICE.list_plans(
            target_alias=_optional_str(args.get("target_alias")),
            status=_optional_str(args.get("status")),
            limit=int(args.get("limit", 50)),
        )
    if name in {"remote_get_plan", "ssh_get_plan"}:
        return SERVICE.get_plan(plan_id=str(args.get("plan_id", "")))
    if name in {"remote_approve_plan", "ssh_approve_plan"}:
        return SERVICE.approve_plan(
            plan_id=str(args.get("plan_id", "")),
            plan_hash=_optional_str(args.get("plan_hash")),
            approved_by=str(args.get("approved_by", "mcp-client")),
            comment=_optional_str(args.get("comment", args.get("approval_note"))),
        )
    if name in {"remote_reject_plan", "ssh_reject_plan"}:
        return SERVICE.reject_plan(
            plan_id=str(args.get("plan_id", "")),
            rejected_by=str(args.get("rejected_by", "mcp-client")),
            reason=_optional_str(args.get("reason")),
        )
    if name in {"remote_execute_plan", "ssh_execute_plan"}:
        return SERVICE.execute_plan(
            plan_id=str(args.get("plan_id", "")),
            plan_hash=_optional_str(args.get("plan_hash")),
            actor=str(args.get("actor", "mcp-client")),
        )
    if name == "remote_start_transfer":
        return SERVICE.start_transfer(
            plan_id=str(args.get("plan_id", "")),
            plan_hash=_optional_str(args.get("plan_hash")),
            step_id=str(args.get("step_id", "")),
            actor=str(args.get("actor", "mcp-client")),
        )
    if name == "remote_get_transfer":
        return SERVICE.get_transfer(transfer_id=str(args.get("transfer_id", "")))
    if name == "remote_cancel_transfer":
        return SERVICE.cancel_transfer(
            transfer_id=str(args.get("transfer_id", "")),
            reason=_optional_str(args.get("reason")),
            actor=str(args.get("actor", "mcp-client")),
        )
    if name == "remote_list_transfers":
        return SERVICE.list_transfers(
            target_alias=_optional_str(args.get("target_alias")),
            status=_optional_str(args.get("status")),
            limit=int(args.get("limit", 20)),
        )
    if name == "remote_run_instruction":
        return SERVICE.run_instruction(
            target_alias=str(args.get("target_alias", "")),
            instruction_data=_dict(args.get("instruction")),
            actor=str(args.get("actor", "mcp-client")),
        )
    if name in {"remote_list_audit_events", "ssh_read_audit_log"}:
        return SERVICE.list_audit_events(
            target_alias=_optional_str(args.get("target_alias")),
            plan_id=_optional_str(args.get("plan_id")),
            run_id=_optional_str(args.get("run_id")),
            event_type=_optional_str(args.get("event_type", args.get("event_filter"))),
            limit=int(args.get("limit", 50)),
        )
    raise ValueError(f"Unknown tool: {name}")


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("expected object")
    return value


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("expected list")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError("expected list of objects")
    return value


def _optional_str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


if __name__ == "__main__":
    main()
