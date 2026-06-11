from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from typing import Any

from backend.ssh.models import ConnectionTarget
from backend.ssh.sftp import (
    compute_remote_hash,
    remote_file_exists,
    upload_file_with_method,
)

from .audit_store import AuditStore
from .models import AuditEvent, Instruction, PlanStep
from .plan_store import PlanStore
from .policy import preview_instruction, redact_text
from .transfer_store import TransferStore
from .upload_utils import (
    MAX_UPLOAD_BYTES,
    RemoteReplaceError,
    build_backup_path,
    build_rename_new_path,
    check_timeout,
    chmod_remote,
    delete_remote,
    file_sha256,
    rename_remote,
    replace_remote,
    restore_backup,
    set_transport_timeout,
    validate_local_file,
    validate_remote_path,
)


MAX_RUNNING_TRANSFERS = 2
MAX_RUNNING_TRANSFERS_PER_TARGET = 1
PROGRESS_UPDATE_INTERVAL_SECONDS = 0.5
PROGRESS_UPDATE_BYTES = 4 * 1024 * 1024
PROGRESS_HEARTBEAT_SECONDS = 60.0


class TransferCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class UploadJob:
    transfer_id: str
    target: ConnectionTarget
    instruction: Instruction
    step: PlanStep
    actor: str
    target_alias: str
    plan_id: str


class TransferWorker:
    def __init__(
        self,
        *,
        transfer_store: TransferStore,
        audit_store: AuditStore,
        pool: object | None,
        plan_store: PlanStore | None = None,
        max_workers: int = MAX_RUNNING_TRANSFERS,
    ) -> None:
        self.transfer_store = transfer_store
        self.audit_store = audit_store
        self.pool = pool
        self.plan_store = plan_store
        self._active_lock = Lock()
        self._active_connections: dict[str, object] = {}
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="transfer",
        )

    def can_start(self, target_alias: str) -> tuple[bool, str | None]:
        total, by_target = self.transfer_store.active_counts()
        if total >= MAX_RUNNING_TRANSFERS:
            return False, "too_many_transfers"
        if by_target.get(target_alias, 0) >= MAX_RUNNING_TRANSFERS_PER_TARGET:
            return False, "too_many_transfers_for_target"
        return True, None

    def submit_upload(self, job: UploadJob) -> None:
        self.executor.submit(self.run_upload_job, job)

    def cancel_transfer(self, transfer_id: str) -> bool:
        with self._active_lock:
            conn = self._active_connections.get(transfer_id)
        if conn is None:
            return False
        _close_connection(conn)
        return True

    def run_upload_job(self, job: UploadJob) -> None:
        instruction = job.instruction
        preview = preview_instruction(instruction).display
        started_at = time.time()
        conn = None
        temp_remote_path = ""
        backup_remote_path = ""
        actual_remote_path = instruction.remote_path or ""
        backed_up = False
        bytes_transferred = 0
        local_sha256 = ""
        file_size = 0
        try:
            self._raise_if_cancelled(job)
            self.transfer_store.mark_status(job.transfer_id, "running")
            self.audit_store.append_event(
                AuditEvent(
                    event_type="step_started",
                    actor=job.actor,
                    target_alias=job.target_alias,
                    plan_id=job.plan_id,
                    step_id=job.step.id,
                    instruction_kind=instruction.kind,
                    instruction_preview=preview,
                    risk_level=job.step.risk_level,
                    metadata={
                        "transfer_id": job.transfer_id,
                        "upload_method": instruction.upload_method,
                    },
                )
            )
            local_path = job.transfer_id and self.transfer_store.get(job.transfer_id)
            if local_path is None:
                raise KeyError(f"Transfer '{job.transfer_id}' not found")
            resolved_local_path = local_path.local_path
            remote_path = instruction.remote_path or ""
            if not resolved_local_path:
                raise ValueError("local_path is required")
            if not remote_path:
                raise ValueError("remote_path is required")
            remote_err = validate_remote_path(remote_path)
            if remote_err:
                raise ValueError(remote_err)
            from pathlib import Path

            local_file = Path(resolved_local_path)
            local_err = validate_local_file(local_file)
            if local_err:
                raise ValueError(local_err)
            file_size = local_file.stat().st_size
            if file_size > MAX_UPLOAD_BYTES:
                raise ValueError(
                    f"file size {file_size} exceeds limit of {MAX_UPLOAD_BYTES}"
                )
            self._raise_if_cancelled(job)
            local_sha256 = file_sha256(local_file)
            self.transfer_store.mark_status(
                job.transfer_id,
                "running",
                bytes_total=file_size,
                local_sha256=local_sha256,
            )
            self._raise_if_cancelled(job)
            if self.pool is None:
                raise RuntimeError("connection pool is not configured")
            conn = self.pool.acquire(
                job.target,
                purpose="sftp",
                timeout=instruction.timeout_seconds,
            )
            self._register_active_connection(job.transfer_id, conn)
            self._raise_if_cancelled(job)
            conflict = remote_file_exists(conn, remote_path)
            if conflict:
                if instruction.conflict_policy == "fail":
                    self._mark_failed(
                        job,
                        status="conflict",
                        error_type="conflict",
                        error_message="target file exists and conflict_policy is fail",
                        metadata={
                            "remote_path": remote_path,
                            "bytes_total": file_size,
                            "local_sha256": local_sha256,
                            "conflict_detected": True,
                        },
                    )
                    return
                if instruction.conflict_policy == "backup_then_overwrite":
                    self._raise_if_cancelled(job)
                    backup_remote_path = build_backup_path(
                        remote_path,
                        instruction.backup_suffix,
                    )
                    rename_remote(conn, remote_path, backup_remote_path)
                    backed_up = True
                if instruction.conflict_policy == "rename_new":
                    self._raise_if_cancelled(job)
                    actual_remote_path = build_rename_new_path(remote_path)
            temp_remote_path = local_path.temp_remote_path or actual_remote_path
            self.transfer_store.mark_status(
                job.transfer_id,
                "running",
                actual_remote_path=actual_remote_path,
                temp_remote_path=temp_remote_path,
                backup_remote_path=backup_remote_path,
            )

            deadline = started_at + instruction.timeout_seconds
            set_transport_timeout(conn, max(1, deadline - time.time()))
            self._raise_if_cancelled(job)
            last_progress_at = 0.0
            last_progress_bytes = 0

            def transfer_callback(transferred: int, total: int) -> None:
                nonlocal bytes_transferred, last_progress_at, last_progress_bytes
                self._raise_if_cancelled(job)
                check_timeout(deadline, "upload")
                bytes_transferred = transferred
                now = time.time()
                if (
                    now - last_progress_at >= PROGRESS_UPDATE_INTERVAL_SECONDS
                    or transferred - last_progress_bytes >= PROGRESS_UPDATE_BYTES
                    or transferred >= total
                ):
                    self.transfer_store.update_progress(
                        job.transfer_id,
                        transferred,
                        total,
                    )
                    last_progress_at = now
                    last_progress_bytes = transferred

            def transfer_checkpoint() -> None:
                nonlocal last_progress_at
                self._raise_if_cancelled(job)
                check_timeout(deadline, "upload")
                now = time.time()
                if (
                    file_size > 0
                    and now - last_progress_at >= PROGRESS_HEARTBEAT_SECONDS
                ):
                    self.transfer_store.update_progress(
                        job.transfer_id,
                        bytes_transferred,
                        file_size,
                    )
                    last_progress_at = now

            upload_file_with_method(
                conn,
                resolved_local_path,
                temp_remote_path,
                method=instruction.upload_method,
                callback=transfer_callback,
                resume=instruction.atomic,
                checkpoint=transfer_checkpoint,
            )
            bytes_transferred = max(bytes_transferred, file_size)
            self.transfer_store.update_progress(
                job.transfer_id,
                bytes_transferred,
                file_size,
            )
            self._raise_if_cancelled(job)

            if instruction.mode:
                self._raise_if_cancelled(job)
                chmod_remote(conn, temp_remote_path, instruction.mode)
            remote_sha256 = ""
            if instruction.verify:
                self._raise_if_cancelled(job)
                self.transfer_store.mark_status(job.transfer_id, "verifying")
                check_timeout(deadline, "upload + verify")
                set_transport_timeout(conn, max(1, deadline - time.time()))
                remote_sha256 = compute_remote_hash(conn, temp_remote_path)
                if remote_sha256 != local_sha256:
                    cleanup_failed = not delete_remote(conn, temp_remote_path)
                    if backed_up:
                        restore_backup(conn, backup_remote_path, remote_path)
                    self._mark_failed(
                        job,
                        status="failed",
                        error_type="sha256_mismatch",
                        error_message=(
                            f"sha256 mismatch: local={local_sha256[:16]}... "
                            f"remote={remote_sha256[:16]}..."
                        ),
                        cleanup_failed=cleanup_failed,
                        metadata={
                            "local_sha256": local_sha256,
                            "remote_sha256": remote_sha256,
                            "backup_restored": backed_up,
                        },
                    )
                    return

            self._raise_if_cancelled(job)
            self.transfer_store.mark_status(job.transfer_id, "renaming")
            if instruction.atomic:
                check_timeout(deadline, "rename")
                if conflict and instruction.conflict_policy == "overwrite":
                    replace_result = replace_remote(
                        conn,
                        temp_remote_path,
                        actual_remote_path,
                    )
                    if replace_result.backup_path:
                        backup_remote_path = replace_result.backup_path
                    cleanup_failed = replace_result.backup_cleanup_failed
                else:
                    rename_remote(conn, temp_remote_path, actual_remote_path)
                    cleanup_failed = False
            else:
                cleanup_failed = False

            finished_at = time.time()
            self.transfer_store.mark_succeeded(
                job.transfer_id,
                actual_remote_path=actual_remote_path,
                temp_remote_path=temp_remote_path if instruction.atomic else "",
                backup_remote_path=backup_remote_path,
                local_sha256=local_sha256,
                remote_sha256=remote_sha256 or None,
                transfer_finished_at=finished_at,
                cleanup_failed=cleanup_failed,
            )
            self._update_plan_transfer_status(job, "succeeded", clear_active=True)
            self.audit_store.append_event(
                AuditEvent(
                    event_type="step_finished",
                    actor=job.actor,
                    target_alias=job.target_alias,
                    plan_id=job.plan_id,
                    step_id=job.step.id,
                    instruction_kind=instruction.kind,
                    instruction_preview=preview,
                    risk_level=job.step.risk_level,
                    elapsed_seconds=round(finished_at - started_at, 3),
                    metadata={"transfer_id": job.transfer_id},
                )
            )
        except TransferCancelled as exc:
            cleanup_failed = self._cleanup_temp_for_failure(
                conn,
                temp_remote_path,
                instruction,
            )
            backup_restored = False
            if backed_up and conn is not None:
                backup_restored = restore_backup(
                    conn,
                    backup_remote_path,
                    instruction.remote_path or "",
                )
            self._mark_failed(
                job,
                status="cancelled",
                error_type=type(exc).__name__,
                error_message=str(exc),
                cleanup_failed=cleanup_failed,
                metadata={
                    "bytes_transferred": bytes_transferred,
                    "backup_remote_path": backup_remote_path,
                    "backup_restored": backup_restored,
                },
            )
        except TimeoutError as exc:
            cleanup_failed = self._cleanup_temp_for_failure(
                conn,
                temp_remote_path,
                instruction,
            )
            self._mark_failed(
                job,
                status="timed_out",
                error_type=type(exc).__name__,
                error_message=str(exc),
                cleanup_failed=cleanup_failed,
                metadata={"bytes_transferred": bytes_transferred},
            )
        except Exception as exc:
            if self.transfer_store.is_cancel_requested(job.transfer_id):
                cleanup_failed = self._cleanup_temp_for_failure(
                    conn,
                    temp_remote_path,
                    instruction,
                )
                if backed_up and conn is not None:
                    restore_backup(
                        conn,
                        backup_remote_path,
                        instruction.remote_path or "",
                    )
                self._mark_failed(
                    job,
                    status="cancelled",
                    error_type=type(exc).__name__,
                    error_message="upload cancelled by user",
                    cleanup_failed=cleanup_failed,
                    metadata={
                        "bytes_total": file_size,
                        "bytes_transferred": bytes_transferred,
                        "backup_remote_path": backup_remote_path,
                        "backup_restored": backed_up,
                    },
                )
                return
            if isinstance(exc, RemoteReplaceError) and exc.backup_path:
                backup_remote_path = exc.backup_path
            cleanup_failed = self._cleanup_temp_for_failure(
                conn,
                temp_remote_path,
                instruction,
            )
            if backed_up and conn is not None:
                restore_backup(conn, backup_remote_path, instruction.remote_path or "")
            self._mark_failed(
                job,
                status="failed",
                error_type=type(exc).__name__,
                error_message=redact_text(str(exc), instruction.redaction_patterns),
                cleanup_failed=cleanup_failed,
                metadata={
                    "bytes_total": file_size,
                    "bytes_transferred": bytes_transferred,
                    "local_sha256": local_sha256,
                    "backup_remote_path": backup_remote_path,
                    "backup_restored": backed_up,
                },
            )
        finally:
            self._unregister_active_connection(job.transfer_id)
            if conn is not None and self.pool is not None:
                try:
                    self.pool.release(conn)
                except Exception:
                    pass

    def _raise_if_cancelled(self, job: UploadJob) -> None:
        if self.transfer_store.is_cancel_requested(job.transfer_id):
            raise TransferCancelled("upload cancelled by user")

    def _register_active_connection(self, transfer_id: str, conn: object) -> None:
        with self._active_lock:
            self._active_connections[transfer_id] = conn

    def _unregister_active_connection(self, transfer_id: str) -> None:
        with self._active_lock:
            self._active_connections.pop(transfer_id, None)

    def _mark_failed(
        self,
        job: UploadJob,
        *,
        status: str,
        error_type: str,
        error_message: str,
        cleanup_failed: bool = False,
        metadata: dict[str, object] | None = None,
    ) -> None:
        record = self.transfer_store.mark_failed(
            job.transfer_id,
            status=status,  # type: ignore[arg-type]
            error_type=error_type,
            error_message=error_message,
            cleanup_failed=cleanup_failed,
        )
        self._update_plan_transfer_status(job, status, clear_active=True)
        self.audit_store.append_event(
            AuditEvent(
                event_type="step_failed",
                actor=job.actor,
                target_alias=job.target_alias,
                plan_id=job.plan_id,
                step_id=job.step.id,
                instruction_kind=job.instruction.kind,
                instruction_preview=preview_instruction(job.instruction).display,
                risk_level=job.step.risk_level,
                elapsed_seconds=record.elapsed_seconds,
                error_type=error_type,
                error_message=error_message,
                metadata={
                    "transfer_id": job.transfer_id,
                    "upload_method": job.instruction.upload_method,
                    **(metadata or {}),
                },
            )
        )

    def _update_plan_transfer_status(
        self,
        job: UploadJob,
        status: str,
        *,
        clear_active: bool,
    ) -> None:
        if self.plan_store is None:
            return
        plan = self.plan_store.get(job.plan_id)
        if plan is None:
            return
        metadata = {**plan.metadata, "last_transfer_status": status}
        if clear_active and metadata.get("active_transfer_id") == job.transfer_id:
            metadata.pop("active_transfer_id", None)
            metadata.pop("active_transfer_step_id", None)
        from dataclasses import replace

        self.plan_store.save(replace(plan, metadata=metadata))

    def _cleanup_temp(self, conn: object | None, temp_remote_path: str) -> bool:
        if conn is None or not temp_remote_path:
            return False
        return not delete_remote(conn, temp_remote_path)

    def _cleanup_temp_for_failure(
        self,
        conn: object | None,
        temp_remote_path: str,
        instruction: Instruction,
    ) -> bool:
        if instruction.atomic and instruction.upload_method == "sftp":
            return False
        return self._cleanup_temp(conn, temp_remote_path)


def _close_connection(conn: object) -> None:
    client = getattr(conn, "client", None)
    _close_quietly(client)
    for aux_client in getattr(conn, "aux_clients", []) or []:
        _close_quietly(aux_client)


def _close_quietly(resource: Any) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
