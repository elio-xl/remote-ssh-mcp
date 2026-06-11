from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.ssh import sftp
from backend import main as backend_main
from backend.remote.audit_store import AuditStore
from backend.remote.models import ExecutionPlan, Instruction, PlanStep
from backend.remote.plan_store import PlanStore
from backend.remote.transfer_store import TransferStore
from backend.remote.transfer_worker import UploadJob, TransferWorker
from backend.remote.upload_utils import temp_path
from backend.ssh.models import ConnectionTarget


class FakePool:
    def __init__(self) -> None:
        self.acquire_calls = 0
        self.release_calls = 0
        self.conn = object()

    def acquire(self, *args: object, **kwargs: object) -> object:
        self.acquire_calls += 1
        return self.conn

    def release(self, conn: object) -> None:
        self.release_calls += 1


class TransferSafetyTests(unittest.TestCase):
    def test_temp_path_is_stable_for_upload_resume(self) -> None:
        first = temp_path("/opt/app/artifact.tar.gz")
        second = temp_path("/opt/app/artifact.tar.gz")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("/opt/app/artifact.tar.gz.part."))

    def test_upload_file_skips_paramiko_confirm_stat_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local_file = Path(tmp) / "artifact.txt"
            local_file.write_text("payload", encoding="utf-8")

            class RemoteFile:
                def __init__(self) -> None:
                    self.written = bytearray()

                def __enter__(self) -> RemoteFile:
                    return self

                def __exit__(self, *args: object) -> None:
                    return None

                def write(self, data: bytes) -> None:
                    self.written.extend(data)

                def flush(self) -> None:
                    return None

            class Sftp:
                def __init__(self) -> None:
                    self.file = RemoteFile()
                    self.stat_calls = 0
                    self.closed = False

                def stat(self, path: str) -> object:
                    self.stat_calls += 1
                    raise FileNotFoundError("[Errno 2] No such file")

                def open(self, path: str, mode: str) -> RemoteFile:
                    self.open_path = path
                    self.open_mode = mode
                    return self.file

                def close(self) -> None:
                    self.closed = True

            class Client:
                def __init__(self) -> None:
                    self.sftp = Sftp()

                def open_sftp(self) -> Sftp:
                    return self.sftp

            class Conn:
                def __init__(self) -> None:
                    self.client = Client()

            conn = Conn()
            sftp.upload_file(  # type: ignore[arg-type]
                conn,
                str(local_file),
                "/tmp/remote",
            )
            self.assertEqual(conn.client.sftp.open_path, "/tmp/remote")
            self.assertEqual(conn.client.sftp.open_mode, "wb")
            self.assertEqual(bytes(conn.client.sftp.file.written), b"payload")
            self.assertEqual(conn.client.sftp.stat_calls, 1)
            self.assertTrue(conn.client.sftp.closed)

    def test_upload_file_resumes_existing_sftp_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local_file = Path(tmp) / "artifact.txt"
            local_file.write_text("payload", encoding="utf-8")

            class Stat:
                st_size = 4

            class RemoteFile:
                def __init__(self, body: bytes = b"") -> None:
                    self.body = body
                    self.cursor = 0
                    self.written = bytearray()

                def __enter__(self) -> RemoteFile:
                    return self

                def __exit__(self, *args: object) -> None:
                    return None

                def write(self, data: bytes) -> None:
                    self.written.extend(data)

                def read(self, size: int) -> bytes:
                    chunk = self.body[self.cursor : self.cursor + size]
                    self.cursor += len(chunk)
                    return chunk

                def flush(self) -> None:
                    return None

            class Sftp:
                def __init__(self) -> None:
                    self.file = RemoteFile()
                    self.reader = RemoteFile(b"payl")
                    self.closed = False

                def stat(self, path: str) -> Stat:
                    return Stat()

                def open(self, path: str, mode: str) -> RemoteFile:
                    self.open_path = path
                    self.open_mode = mode
                    if mode == "rb":
                        return self.reader
                    return self.file

                def close(self) -> None:
                    self.closed = True

            class Client:
                def __init__(self) -> None:
                    self.sftp = Sftp()

                def open_sftp(self) -> Sftp:
                    return self.sftp

            class Conn:
                def __init__(self) -> None:
                    self.client = Client()

            progress: list[tuple[int, int]] = []
            conn = Conn()
            sftp.upload_file(
                conn,  # type: ignore[arg-type]
                str(local_file),
                "/tmp/remote.part",
                callback=lambda done, total: progress.append((done, total)),
            )

            self.assertEqual(conn.client.sftp.open_mode, "ab")
            self.assertEqual(bytes(conn.client.sftp.file.written), b"oad")
            self.assertEqual(progress[-1], (7, 7))
            self.assertTrue(conn.client.sftp.closed)

    def test_upload_file_restarts_when_sftp_partial_prefix_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local_file = Path(tmp) / "artifact.txt"
            local_file.write_text("payload", encoding="utf-8")

            class Stat:
                st_size = 4

            class RemoteFile:
                def __init__(self, body: bytes = b"") -> None:
                    self.body = body
                    self.cursor = 0
                    self.written = bytearray()

                def __enter__(self) -> RemoteFile:
                    return self

                def __exit__(self, *args: object) -> None:
                    return None

                def read(self, size: int) -> bytes:
                    chunk = self.body[self.cursor : self.cursor + size]
                    self.cursor += len(chunk)
                    return chunk

                def write(self, data: bytes) -> None:
                    self.written.extend(data)

                def flush(self) -> None:
                    return None

            class Sftp:
                def __init__(self) -> None:
                    self.file = RemoteFile()
                    self.reader = RemoteFile(b"xxxx")

                def stat(self, path: str) -> Stat:
                    return Stat()

                def open(self, path: str, mode: str) -> RemoteFile:
                    self.open_path = path
                    self.open_mode = mode
                    if mode == "rb":
                        return self.reader
                    return self.file

                def close(self) -> None:
                    return None

            class Client:
                def __init__(self) -> None:
                    self.sftp = Sftp()

                def open_sftp(self) -> Sftp:
                    return self.sftp

            class Conn:
                def __init__(self) -> None:
                    self.client = Client()

            progress: list[tuple[int, int]] = []
            conn = Conn()
            sftp.upload_file(
                conn,  # type: ignore[arg-type]
                str(local_file),
                "/tmp/remote.part",
                callback=lambda done, total: progress.append((done, total)),
            )

            self.assertEqual(conn.client.sftp.open_mode, "wb")
            self.assertEqual(bytes(conn.client.sftp.file.written), b"payload")
            self.assertEqual(progress[-1], (7, 7))

    def test_upload_file_with_method_can_use_scp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local_file = Path(tmp) / "artifact.txt"
            local_file.write_text("payload", encoding="utf-8")

            class Channel:
                def __init__(self) -> None:
                    self.sent = bytearray()
                    self.commands: list[str] = []
                    self.closed = False

                def exec_command(self, command: str) -> None:
                    self.commands.append(command)

                def recv(self, size: int) -> bytes:
                    return b"\x00"

                def sendall(self, data: bytes) -> None:
                    self.sent.extend(data)

                def close(self) -> None:
                    self.closed = True

            class Transport:
                def __init__(self) -> None:
                    self.channel = Channel()

                def open_session(self) -> Channel:
                    return self.channel

            class Client:
                def __init__(self) -> None:
                    self.transport = Transport()
                    self.opened_sftp = False

                def get_transport(self) -> Transport:
                    return self.transport

                def open_sftp(self) -> object:
                    self.opened_sftp = True
                    raise AssertionError("SFTP should not be used")

            class Conn:
                def __init__(self) -> None:
                    self.client = Client()

            progress: list[tuple[int, int]] = []
            checkpoints: list[str] = []
            conn = Conn()
            sftp.upload_file_with_method(
                conn,  # type: ignore[arg-type]
                str(local_file),
                "/tmp/artifact.txt",
                method="scp",
                callback=lambda done, total: progress.append((done, total)),
                checkpoint=lambda: checkpoints.append("checked"),
            )

            channel = conn.client.transport.channel
            self.assertEqual(channel.commands, ["scp -t /tmp/artifact.txt"])
            self.assertIn(b"C0644 7 artifact.txt\n", channel.sent)
            self.assertIn(b"payload", channel.sent)
            self.assertTrue(channel.sent.endswith(b"\x00"))
            self.assertEqual(progress[-1], (7, 7))
            self.assertGreaterEqual(len(checkpoints), 4)
            self.assertFalse(conn.client.opened_sftp)
            self.assertTrue(channel.closed)

    def test_scp_upload_checks_progress_while_channel_waits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local_file = Path(tmp) / "artifact.txt"
            local_file.write_text("payload", encoding="utf-8")

            class Channel:
                def __init__(self) -> None:
                    self.sent = bytearray()
                    self.acks = [b"\x00", b"\x00", b"\x00"]
                    self.recv_ready_calls = 0
                    self.send_ready_calls = 0
                    self.closed = False

                def settimeout(self, timeout: float) -> None:
                    self.timeout = timeout

                def exec_command(self, command: str) -> None:
                    self.command = command

                def recv_ready(self) -> bool:
                    self.recv_ready_calls += 1
                    return self.recv_ready_calls % 2 == 0

                def recv(self, size: int) -> bytes:
                    return self.acks.pop(0)

                def send_ready(self) -> bool:
                    self.send_ready_calls += 1
                    return self.send_ready_calls % 2 == 0

                def send(self, data: bytes) -> int:
                    self.sent.extend(data)
                    return len(data)

                def exit_status_ready(self) -> bool:
                    return False

                def close(self) -> None:
                    self.closed = True

            class Transport:
                def __init__(self) -> None:
                    self.channel = Channel()

                def open_session(self) -> Channel:
                    return self.channel

            class Client:
                def __init__(self) -> None:
                    self.transport = Transport()

                def get_transport(self) -> Transport:
                    return self.transport

            class Conn:
                def __init__(self) -> None:
                    self.client = Client()

            checkpoints: list[str] = []
            conn = Conn()
            with patch("backend.ssh.sftp.time.sleep"):
                sftp.upload_file_with_method(
                    conn,  # type: ignore[arg-type]
                    str(local_file),
                    "/tmp/artifact.txt",
                    method="scp",
                    checkpoint=lambda: checkpoints.append("checked"),
                )

            channel = conn.client.transport.channel
            self.assertGreater(channel.recv_ready_calls, 3)
            self.assertGreater(channel.send_ready_calls, 3)
            self.assertGreater(len(checkpoints), 6)
            self.assertIn(b"payload", channel.sent)

    def test_remote_hash_prefers_remote_sha256_command(self) -> None:
        digest = "a" * 64

        class Channel:
            def recv_exit_status(self) -> int:
                return 0

        class Stream:
            channel = Channel()

            def __init__(self, body: str = "") -> None:
                self.body = body

            def read(self) -> bytes:
                return self.body.encode("utf-8")

        class Client:
            opened_sftp = False

            def exec_command(self, command: str, timeout: int) -> tuple[None, Stream, Stream]:
                self.command = command
                self.timeout = timeout
                return None, Stream(f"{digest}  /tmp/file\n"), Stream()

            def open_sftp(self) -> object:
                self.opened_sftp = True
                raise AssertionError("SFTP fallback should not be used")

        class Conn:
            def __init__(self) -> None:
                self.client = Client()

        conn = Conn()
        self.assertEqual(sftp.compute_remote_hash(conn, "/tmp/file"), digest)  # type: ignore[arg-type]
        self.assertIn("sha256sum", conn.client.command)
        self.assertFalse(conn.client.opened_sftp)

    def test_plan_hash_ignores_transfer_runtime_metadata(self) -> None:
        step = PlanStep(
            instruction=Instruction(
                kind="sftp_put",
                local_path="./artifact.tar.gz",
                remote_path="/opt/app/artifact.tar.gz",
            ),
            risk_level="high",
        )
        plan = ExecutionPlan(
            target_alias="prod",
            goal="upload artifact",
            steps=[step],
            risk_level="high",
            requires_approval=True,
            metadata={"remote_conflicts": []},
        )
        original_hash = plan.plan_hash
        updated = ExecutionPlan(
            id=plan.id,
            target_alias=plan.target_alias,
            goal=plan.goal,
            summary=plan.summary,
            steps=plan.steps,
            risk_level=plan.risk_level,
            requires_approval=plan.requires_approval,
            created_by=plan.created_by,
            created_at=plan.created_at,
            expires_at=plan.expires_at,
            metadata={
                **plan.metadata,
                "active_transfer_id": "transfer-123",
                "active_transfer_step_id": step.id,
                "last_transfer_status": "running",
            },
        )
        self.assertEqual(original_hash, updated.plan_hash)

    def test_create_upload_is_atomic_for_duplicate_step_and_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TransferStore(Path(tmp) / "transfers.json")
            first, error, existing = store.create_upload_if_allowed(
                max_total_active=1,
                max_active_per_target=1,
                target_alias="prod",
                plan_id="plan-1",
                step_id="step-1",
                actor="test",
                local_path="/tmp/a",
                local_path_display="a",
                remote_path="/tmp/a",
                actual_remote_path="/tmp/a",
                temp_remote_path="/tmp/a.tmp",
                conflict_policy="fail",
                atomic=True,
                verify=True,
                bytes_total=1,
            )
            self.assertIsNotNone(first)
            self.assertIsNone(error)
            self.assertIsNone(existing)

            second, error, existing = store.create_upload_if_allowed(
                max_total_active=1,
                max_active_per_target=1,
                target_alias="prod",
                plan_id="plan-1",
                step_id="step-1",
                actor="test",
                local_path="/tmp/b",
                local_path_display="b",
                remote_path="/tmp/b",
                actual_remote_path="/tmp/b",
                temp_remote_path="/tmp/b.tmp",
                conflict_policy="fail",
                atomic=True,
                verify=True,
                bytes_total=1,
            )
            self.assertIsNone(second)
            self.assertEqual(error, "transfer_already_running")
            self.assertIsNotNone(existing)
            self.assertEqual(existing.transfer_id, first.transfer_id)

    def test_cancel_before_worker_starts_does_not_acquire_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transfer_store = TransferStore(Path(tmp) / "transfers.json")
            audit_store = AuditStore(Path(tmp) / "audit.jsonl")
            plan_store = PlanStore(Path(tmp) / "plans.json")
            record = transfer_store.create_upload(
                target_alias="prod",
                plan_id="plan-1",
                step_id="step-1",
                actor="test",
                local_path="/tmp/nonexistent",
                local_path_display="nonexistent",
                remote_path="/tmp/nonexistent",
                actual_remote_path="/tmp/nonexistent",
                temp_remote_path="/tmp/nonexistent.tmp",
                conflict_policy="fail",
                atomic=True,
                verify=True,
                bytes_total=1,
            )
            transfer_store.request_cancel(record.transfer_id, "stop")
            pool = FakePool()
            worker = TransferWorker(
                transfer_store=transfer_store,
                audit_store=audit_store,
                pool=pool,
                plan_store=plan_store,
            )
            worker.run_upload_job(_job(record.transfer_id))
            final = transfer_store.get(record.transfer_id)
            self.assertIsNotNone(final)
            self.assertEqual(final.status, "cancelled")
            self.assertEqual(pool.acquire_calls, 0)

    def test_cancel_after_upload_prevents_verify_and_rename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local_file = Path(tmp) / "artifact.txt"
            local_file.write_text("payload", encoding="utf-8")
            transfer_store = TransferStore(Path(tmp) / "transfers.json")
            audit_store = AuditStore(Path(tmp) / "audit.jsonl")
            plan_store = PlanStore(Path(tmp) / "plans.json")
            record = transfer_store.create_upload(
                target_alias="prod",
                plan_id="plan-1",
                step_id="step-1",
                actor="test",
                local_path=str(local_file),
                local_path_display="artifact.txt",
                remote_path="/tmp/artifact.txt",
                actual_remote_path="/tmp/artifact.txt",
                temp_remote_path="/tmp/artifact.txt.tmp",
                conflict_policy="fail",
                atomic=True,
                verify=True,
                bytes_total=local_file.stat().st_size,
            )
            pool = FakePool()
            worker = TransferWorker(
                transfer_store=transfer_store,
                audit_store=audit_store,
                pool=pool,
                plan_store=plan_store,
            )

            def fake_upload(
                conn: object,
                local_path: str,
                remote_path: str,
                method: str,
                resume: bool,
                checkpoint: object,
                callback: object,
            ) -> None:
                self.assertEqual(method, "sftp")
                self.assertTrue(resume)
                callback(  # type: ignore[misc]
                    local_file.stat().st_size,
                    local_file.stat().st_size,
                )
                transfer_store.request_cancel(record.transfer_id, "stop after upload")

            with patch(
                "backend.remote.transfer_worker.remote_file_exists",
                return_value=False,
            ), patch(
                "backend.remote.transfer_worker.upload_file_with_method",
                side_effect=fake_upload,
            ), patch(
                "backend.remote.transfer_worker.delete_remote",
                return_value=True,
            ) as delete_remote, patch(
                "backend.remote.transfer_worker.compute_remote_hash"
            ) as compute_hash, patch(
                "backend.remote.transfer_worker.rename_remote"
            ) as rename_remote:
                worker.run_upload_job(
                    _job(record.transfer_id, local_path=str(local_file))
                )

            final = transfer_store.get(record.transfer_id)
            self.assertIsNotNone(final)
            self.assertEqual(final.status, "cancelled")
            delete_remote.assert_not_called()
            compute_hash.assert_not_called()
            rename_remote.assert_not_called()
            self.assertEqual(pool.release_calls, 1)

    def test_background_upload_throttles_progress_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local_file = Path(tmp) / "artifact.bin"
            local_file.write_bytes(b"x" * (10 * 1024 * 1024))
            transfer_store = TransferStore(Path(tmp) / "transfers.json")
            audit_store = AuditStore(Path(tmp) / "audit.jsonl")
            plan_store = PlanStore(Path(tmp) / "plans.json")
            record = transfer_store.create_upload(
                target_alias="prod",
                plan_id="plan-1",
                step_id="step-1",
                actor="test",
                local_path=str(local_file),
                local_path_display="artifact.bin",
                remote_path="/tmp/artifact.bin",
                actual_remote_path="/tmp/artifact.bin",
                temp_remote_path="/tmp/artifact.bin.tmp",
                conflict_policy="fail",
                atomic=True,
                verify=False,
                bytes_total=local_file.stat().st_size,
            )
            pool = FakePool()
            worker = TransferWorker(
                transfer_store=transfer_store,
                audit_store=audit_store,
                pool=pool,
                plan_store=plan_store,
            )

            def fake_upload(
                conn: object,
                local_path: str,
                remote_path: str,
                method: str,
                resume: bool,
                checkpoint: object,
                callback: object,
            ) -> None:
                self.assertEqual(method, "sftp")
                self.assertTrue(resume)
                total = local_file.stat().st_size
                for transferred in (
                    1 * 1024 * 1024,
                    2 * 1024 * 1024,
                    3 * 1024 * 1024,
                    total,
                ):
                    callback(transferred, total)  # type: ignore[misc]

            with patch(
                "backend.remote.transfer_worker.remote_file_exists",
                return_value=False,
            ), patch(
                "backend.remote.transfer_worker.upload_file_with_method",
                side_effect=fake_upload,
            ), patch(
                "backend.remote.transfer_worker.rename_remote"
            ), patch.object(
                transfer_store,
                "update_progress",
                wraps=transfer_store.update_progress,
            ) as update_progress:
                worker.run_upload_job(
                    _job(
                        record.transfer_id,
                        local_path=str(local_file),
                        verify=False,
                    )
                )

            final = transfer_store.get(record.transfer_id)
            self.assertIsNotNone(final)
            self.assertEqual(final.status, "succeeded")
            self.assertLessEqual(update_progress.call_count, 3)

    def test_backend_mcp_dispatch_exposes_transfer_tools(self) -> None:
        class Service:
            def start_transfer(self, **kwargs: object) -> dict[str, object]:
                return {"tool": "start", **kwargs}

            def get_transfer(self, **kwargs: object) -> dict[str, object]:
                return {"tool": "get", **kwargs}

            def cancel_transfer(self, **kwargs: object) -> dict[str, object]:
                return {"tool": "cancel", **kwargs}

            def list_transfers(self, **kwargs: object) -> dict[str, object]:
                return {"tool": "list", **kwargs}

        service = Service()
        with patch.object(backend_main, "REMOTE_SERVICE", service):
            self.assertEqual(
                backend_main._dispatch_tool(
                    "remote_start_transfer",
                    {
                        "plan_id": "plan-1",
                        "plan_hash": "sha256:x",
                        "step_id": "step-1",
                    },
                )["tool"],
                "start",
            )
            self.assertEqual(
                backend_main._dispatch_tool(
                    "remote_get_transfer",
                    {"transfer_id": "transfer-1"},
                )["tool"],
                "get",
            )
            self.assertEqual(
                backend_main._dispatch_tool(
                    "remote_cancel_transfer",
                    {"transfer_id": "transfer-1"},
                )["tool"],
                "cancel",
            )
            self.assertEqual(
                backend_main._dispatch_tool(
                    "remote_list_transfers",
                    {"target_alias": "prod"},
                )["tool"],
                "list",
            )


def _job(
    transfer_id: str,
    local_path: str = "/tmp/nonexistent",
    verify: bool = True,
) -> UploadJob:
    instruction = Instruction(
        kind="sftp_put",
        local_path=local_path,
        remote_path="/tmp/artifact.txt",
        timeout_seconds=30,
        verify=verify,
        atomic=True,
    )
    step = PlanStep(id="step-1", instruction=instruction, risk_level="high")
    target = ConnectionTarget(
        alias="prod",
        hostname="127.0.0.1",
        port=22,
        username="user",
        auth_type="key",
    )
    return UploadJob(
        transfer_id=transfer_id,
        target=target,
        instruction=instruction,
        step=step,
        actor="test",
        target_alias="prod",
        plan_id="plan-1",
    )


if __name__ == "__main__":
    unittest.main()
