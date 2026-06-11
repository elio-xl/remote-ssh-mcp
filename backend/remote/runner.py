from __future__ import annotations

import hashlib
import shlex
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass

from backend.ssh.models import ConnectionTarget
from backend.ssh.sftp import (
    compute_remote_hash,
    remote_file_exists,
    upload_file_with_method,
)

from .audit_store import AuditStore
from .models import (
    AuditEvent,
    ExecutionPlan,
    ExecutionRun,
    Instruction,
    PlanStep,
    StepResult,
)
from .policy import classify_instruction, preview_instruction, redact_text
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
    resolve_local_path,
    restore_backup,
    set_transport_timeout,
    temp_path,
    validate_local_file,
    validate_remote_path,
)
from .transfer_worker import PROGRESS_UPDATE_BYTES, PROGRESS_UPDATE_INTERVAL_SECONDS


EXCERPT_LIMIT = 8192
TargetResolver = Callable[[str], ConnectionTarget]


class RemoteRunner:
    def __init__(
        self,
        *,
        audit_store: AuditStore,
        target_resolver: TargetResolver,
        pool: object | None = None,
    ) -> None:
        self.pool = pool
        self.audit_store = audit_store
        self.target_resolver = target_resolver

    def run_instruction(
        self,
        *,
        target_alias: str,
        instruction: Instruction,
        actor: str = "system",
    ) -> ExecutionRun:
        step = PlanStep(
            title="Direct instruction",
            instruction=instruction,
            risk_level=classify_instruction(instruction).risk_level,
        )
        plan = ExecutionPlan(
            target_alias=target_alias,
            goal="direct instruction",
            summary=preview_instruction(instruction).display,
            steps=[step],
            risk_level=step.risk_level,
            requires_approval=False,
            created_by=actor,
        )
        return self.run_plan(plan, actor=actor, direct=True)

    def run_plan(self, plan: ExecutionPlan, *, actor: str = "system", direct: bool = False) -> ExecutionRun:
        run = ExecutionRun(plan_id=None if direct else plan.id, target_alias=plan.target_alias)
        self.audit_store.append_event(
            AuditEvent(
                event_type="run_started",
                actor=actor,
                target_alias=plan.target_alias,
                plan_id=run.plan_id,
                run_id=run.id,
                risk_level=plan.risk_level,
            )
        )

        for step in plan.steps:
            run.current_step_id = step.id
            result = self._run_step(plan, run, step, actor=actor)
            run.step_results.append(result)
            if result.status != "succeeded":
                run.status = result.status
                run.finished_at = time.time()
                self.audit_store.append_event(
                    AuditEvent(
                        event_type="run_failed",
                        actor=actor,
                        target_alias=plan.target_alias,
                        plan_id=run.plan_id,
                        run_id=run.id,
                        step_id=step.id,
                        risk_level=plan.risk_level,
                        error_message=result.error_message,
                    )
                )
                return run

        run.status = "succeeded"
        run.finished_at = time.time()
        self.audit_store.append_event(
            AuditEvent(
                event_type="run_finished",
                actor=actor,
                target_alias=plan.target_alias,
                plan_id=run.plan_id,
                run_id=run.id,
                risk_level=plan.risk_level,
            )
        )
        return run

    def _run_step(self, plan: ExecutionPlan, run: ExecutionRun, step: PlanStep, *, actor: str) -> StepResult:
        instruction = step.instruction
        if instruction is None:
            return StepResult(
                step_id=step.id,
                instruction_kind="shell",
                status="failed",
                error_message="step has no instruction",
            )

        preview = preview_instruction(instruction)
        self.audit_store.append_event(
            AuditEvent(
                event_type="step_started",
                actor=actor,
                target_alias=plan.target_alias,
                plan_id=run.plan_id,
                run_id=run.id,
                step_id=step.id,
                instruction_kind=instruction.kind,
                instruction_preview=preview.display,
                risk_level=step.risk_level,
            )
        )

        policy = classify_instruction(instruction)
        if policy.decision == "block":
            self.audit_store.append_event(
                AuditEvent(
                    event_type="instruction_blocked",
                    actor=actor,
                    target_alias=plan.target_alias,
                    plan_id=run.plan_id,
                    run_id=run.id,
                    step_id=step.id,
                    instruction_kind=instruction.kind,
                    instruction_preview=preview.display,
                    risk_level=policy.risk_level,
                    decision=policy.decision,
                    error_message=policy.reason,
                )
            )
            return StepResult(
                step_id=step.id,
                instruction_kind=instruction.kind,
                status="failed",
                error_message=policy.reason,
            )

        resolved_command: str | None = None
        if instruction.kind == "read_file":
            if not instruction.remote_path:
                return StepResult(step.id, instruction.kind, "failed", error_message="read_file requires remote_path")
            resolved_command = f"cat -- {shlex.quote(instruction.remote_path)}"
        elif instruction.kind == "sftp_put":
            return self._run_sftp_put(plan, run, step, instruction, preview.display, actor)
        elif instruction.kind != "shell":
            message = f"instruction kind '{instruction.kind}' is not implemented in first phase"
            self.audit_store.append_event(
                AuditEvent(
                    event_type="step_failed",
                    actor=actor,
                    target_alias=plan.target_alias,
                    plan_id=run.plan_id,
                    run_id=run.id,
                    step_id=step.id,
                    instruction_kind=instruction.kind,
                    instruction_preview=preview.display,
                    risk_level=step.risk_level,
                    error_type="unsupported_instruction",
                    error_message=message,
                )
            )
            return StepResult(step.id, instruction.kind, "failed", error_message=message)

        started = time.monotonic()
        try:
            target = self.target_resolver(plan.target_alias)
            command_result = exec_command_via_ssh(
                target,
                resolved_command or instruction.command or "",
                timeout=instruction.timeout_seconds,
                workdir=instruction.workdir,
            )
            stdout = _summarize(command_result.stdout, instruction.redaction_patterns)
            stderr = _summarize(command_result.stderr, instruction.redaction_patterns)
            status = "succeeded" if command_result.exit_code == 0 else "failed"
            event_type = "step_finished" if status == "succeeded" else "step_failed"
            self.audit_store.append_event(
                AuditEvent(
                    event_type=event_type,
                    actor=actor,
                    target_alias=plan.target_alias,
                    plan_id=run.plan_id,
                    run_id=run.id,
                    step_id=step.id,
                    instruction_kind=instruction.kind,
                    instruction_preview=preview.display,
                    risk_level=step.risk_level,
                    exit_code=command_result.exit_code,
                    elapsed_seconds=command_result.elapsed_seconds,
                    stdout_digest=stdout["digest"],
                    stderr_digest=stderr["digest"],
                    stdout_excerpt=stdout["excerpt"],
                    stderr_excerpt=stderr["excerpt"],
                    error_message=None if status == "succeeded" else "command exited with non-zero status",
                )
            )
            return StepResult(
                step_id=step.id,
                instruction_kind=instruction.kind,
                status=status,
                exit_code=command_result.exit_code,
                elapsed_seconds=command_result.elapsed_seconds,
                stdout_digest=stdout["digest"],
                stderr_digest=stderr["digest"],
                stdout_excerpt=stdout["excerpt"],
                stderr_excerpt=stderr["excerpt"],
                stdout_truncated=bool(stdout["truncated"]),
                stderr_truncated=bool(stderr["truncated"]),
                error_message=None if status == "succeeded" else "command exited with non-zero status",
            )
        except TimeoutError as exc:
            return self._failed_step(plan, run, step, instruction, preview.display, actor, "timed_out", "timeout", str(exc), time.monotonic() - started)
        except (RuntimeError, ValueError, KeyError) as exc:
            return self._failed_step(plan, run, step, instruction, preview.display, actor, "failed", type(exc).__name__, str(exc), time.monotonic() - started)

    def _failed_step(
        self,
        plan: ExecutionPlan,
        run: ExecutionRun,
        step: PlanStep,
        instruction: Instruction,
        preview: str,
        actor: str,
        status: str,
        error_type: str,
        message: str,
        elapsed: float,
    ) -> StepResult:
        safe_message = redact_text(message, instruction.redaction_patterns)
        self.audit_store.append_event(
            AuditEvent(
                event_type="step_failed",
                actor=actor,
                target_alias=plan.target_alias,
                plan_id=run.plan_id,
                run_id=run.id,
                step_id=step.id,
                instruction_kind=instruction.kind,
                instruction_preview=preview,
                risk_level=step.risk_level,
                elapsed_seconds=round(elapsed, 3),
                error_type=error_type,
                error_message=safe_message,
            )
        )
        return StepResult(
            step_id=step.id,
            instruction_kind=instruction.kind,
            status=status,  # type: ignore[arg-type]
            elapsed_seconds=round(elapsed, 3),
            error_message=safe_message,
        )

    def _run_sftp_put(
        self,
        plan: ExecutionPlan,
        run: ExecutionRun,
        step: PlanStep,
        instruction: Instruction,
        preview: str,
        actor: str,
    ) -> StepResult:
        step_started_at = time.time()
        local_path = resolve_local_path(instruction.local_path or "")
        remote_path = instruction.remote_path or ""

        if not local_path:
            return self._failed_step(plan, run, step, instruction, preview, actor, "failed", "invalid_local_path", "local_path is required", 0)
        if not remote_path:
            return self._failed_step(plan, run, step, instruction, preview, actor, "failed", "invalid_remote_path", "remote_path is required", 0)

        # Validate remote path
        remote_err = validate_remote_path(remote_path)
        if remote_err:
            return self._failed_step(plan, run, step, instruction, preview, actor, "failed", "invalid_remote_path", remote_err, time.time() - step_started_at)

        # Validate local file
        local_err = validate_local_file(local_path)
        if local_err:
            return self._failed_step(plan, run, step, instruction, preview, actor, "failed", "invalid_local_file", local_err, time.time() - step_started_at)

        file_size = local_path.stat().st_size
        if file_size > MAX_UPLOAD_BYTES:
            return self._failed_step(plan, run, step, instruction, preview, actor, "failed", "file_too_large", f"file size {file_size} exceeds limit of {MAX_UPLOAD_BYTES}", time.time() - step_started_at)

        # Compute local sha256
        try:
            local_sha256 = file_sha256(local_path)
        except OSError as exc:
            return self._failed_step(plan, run, step, instruction, preview, actor, "failed", "local_hash_failed", f"cannot hash local file: {exc}", time.time() - step_started_at)

        if self.pool is None:
            return self._failed_step(plan, run, step, instruction, preview, actor, "failed", "no_pool", "connection pool is not configured", time.time() - step_started_at)

        target = self.target_resolver(plan.target_alias)

        try:
            conn = self.pool.acquire(target, purpose="sftp", timeout=instruction.timeout_seconds)
        except Exception as exc:
            return self._failed_step(plan, run, step, instruction, preview, actor, "failed", "pool_acquire_failed", f"cannot acquire SSH connection: {exc}", time.time() - step_started_at)

        temp_remote_path = ""
        backup_remote_path = ""
        actual_remote_path = remote_path
        backed_up = False
        bytes_transferred = 0
        try:
            # Check for remote file conflict
            conflict = remote_file_exists(conn, remote_path)
            if conflict:
                if instruction.conflict_policy == "fail":
                    self.pool.release(conn)
                    meta = {
                        "local_path": str(local_path),
                        "remote_path": remote_path,
                        "local_sha256": local_sha256,
                        "bytes_total": file_size,
                        "conflict_policy": "fail",
                        "conflict_detected": True,
                    }
                    self.audit_store.append_event(
                        AuditEvent(
                            event_type="step_failed", actor=actor, target_alias=plan.target_alias,
                            plan_id=run.plan_id, run_id=run.id, step_id=step.id,
                            instruction_kind=instruction.kind, instruction_preview=preview,
                            risk_level=step.risk_level, elapsed_seconds=round(time.time() - step_started_at, 3),
                            error_type="conflict", error_message="target file exists and conflict_policy is fail",
                            metadata=meta,
                        )
                    )
                    return StepResult(step.id, instruction.kind, "failed", elapsed_seconds=round(time.time() - step_started_at, 3), error_message="target file exists; set conflict_policy to overwrite or backup_then_overwrite", metadata=meta)

                if instruction.conflict_policy == "backup_then_overwrite":
                    backup_remote_path = build_backup_path(remote_path, instruction.backup_suffix)
                    try:
                        rename_remote(conn, remote_path, backup_remote_path)
                        backed_up = True
                    except Exception as exc:
                        self.pool.release(conn)
                        return self._failed_step(plan, run, step, instruction, preview, actor, "failed", "backup_failed", f"cannot backup existing file: {exc}", time.time() - step_started_at)

                if instruction.conflict_policy == "rename_new":
                    actual_remote_path = build_rename_new_path(remote_path)

            # Generate temp path
            if instruction.atomic:
                temp_remote_path = temp_path(remote_path)
            else:
                temp_remote_path = actual_remote_path

            # Upload
            deadline = step_started_at + instruction.timeout_seconds
            set_transport_timeout(conn, max(1, deadline - time.time()))
            last_progress_at = 0.0
            last_progress_bytes = 0

            def transfer_callback(transferred: int, total: int) -> None:
                nonlocal bytes_transferred, last_progress_at, last_progress_bytes
                bytes_transferred = transferred
                now = time.time()
                if (
                    now - last_progress_at >= PROGRESS_UPDATE_INTERVAL_SECONDS
                    or transferred - last_progress_bytes >= PROGRESS_UPDATE_BYTES
                    or transferred >= total
                ):
                    check_timeout(deadline, "upload")
                    last_progress_at = now
                    last_progress_bytes = transferred

            def transfer_checkpoint() -> None:
                check_timeout(deadline, "upload")

            transfer_started = time.time()
            upload_file_with_method(
                conn,
                str(local_path),
                temp_remote_path,
                method=instruction.upload_method,
                callback=transfer_callback,
                resume=instruction.atomic,
                checkpoint=transfer_checkpoint,
            )
            bytes_transferred = max(bytes_transferred, file_size)
            transfer_elapsed = time.time() - transfer_started

            # Chmod if requested
            if instruction.mode:
                chmod_remote(conn, temp_remote_path, instruction.mode)

            # Verify
            if instruction.verify:
                check_timeout(deadline, "upload + verify")
                set_transport_timeout(conn, max(1, deadline - time.time()))
                remote_sha256 = compute_remote_hash(conn, temp_remote_path)
                if remote_sha256 != local_sha256:
                    cleanup_failed = not delete_remote(conn, temp_remote_path)
                    if backed_up:
                        restore_backup(conn, backup_remote_path, remote_path)
                    self.pool.release(conn)
                    meta = {
                        "local_path": str(local_path), "remote_path": remote_path,
                        "temp_remote_path": temp_remote_path, "bytes_total": file_size,
                        "local_sha256": local_sha256, "remote_sha256": remote_sha256,
                        "verified": False, "atomic": instruction.atomic,
                        "backup_restored": backed_up,
                        "cleanup_failed": cleanup_failed,
                    }
                    elapsed = time.time() - step_started_at
                    self.audit_store.append_event(
                        AuditEvent(
                            event_type="step_failed", actor=actor, target_alias=plan.target_alias,
                            plan_id=run.plan_id, run_id=run.id, step_id=step.id,
                            instruction_kind=instruction.kind, instruction_preview=preview,
                            risk_level=step.risk_level, elapsed_seconds=round(elapsed, 3),
                            error_type="sha256_mismatch", error_message=f"sha256 mismatch: local={local_sha256[:16]}... remote={remote_sha256[:16]}...",
                            metadata=meta,
                        )
                    )
                    return StepResult(step.id, instruction.kind, "failed", elapsed_seconds=round(elapsed, 3), error_message=f"sha256 mismatch: local={local_sha256[:16]}... remote={remote_sha256[:16]}...", metadata=meta)
            else:
                remote_sha256 = ""

            # Rename from temp to final
            if instruction.atomic:
                check_timeout(deadline, "rename")
                if conflict and instruction.conflict_policy == "overwrite":
                    replace_result = replace_remote(conn, temp_remote_path, actual_remote_path)
                    if replace_result.backup_path:
                        backup_remote_path = replace_result.backup_path
                    backup_cleanup_failed = replace_result.backup_cleanup_failed
                else:
                    rename_remote(conn, temp_remote_path, actual_remote_path)
                    backup_cleanup_failed = False
            else:
                backup_cleanup_failed = False

            elapsed = time.time() - step_started_at
            meta = {
                "local_path": str(local_path),
                "remote_path": remote_path,
                "actual_remote_path": actual_remote_path,
                "temp_remote_path": temp_remote_path if instruction.atomic else "",
                "backup_remote_path": backup_remote_path,
                "backup_cleanup_failed": backup_cleanup_failed,
                "bytes_total": file_size,
                "bytes_transferred": bytes_transferred,
                "local_sha256": local_sha256,
                "remote_sha256": remote_sha256,
                "atomic": instruction.atomic,
                "verified": instruction.verify,
                "conflict_policy": instruction.conflict_policy,
                "upload_method": instruction.upload_method,
                "mode": instruction.mode,
                "started_at": step_started_at,
                "transfer_started_at": transfer_started,
                "transfer_finished_at": transfer_started + transfer_elapsed,
                "transfer_elapsed_seconds": round(transfer_elapsed, 3),
                "finished_at": time.time(),
                "elapsed_seconds": round(elapsed, 3),
            }
            self.audit_store.append_event(
                AuditEvent(
                    event_type="step_finished", actor=actor, target_alias=plan.target_alias,
                    plan_id=run.plan_id, run_id=run.id, step_id=step.id,
                    instruction_kind=instruction.kind, instruction_preview=preview,
                    risk_level=step.risk_level, elapsed_seconds=round(elapsed, 3),
                    metadata=meta,
                )
            )
            self.pool.release(conn)
            return StepResult(step.id, instruction.kind, "succeeded", elapsed_seconds=round(elapsed, 3), metadata=meta)
        except Exception as exc:
            if isinstance(exc, RemoteReplaceError) and exc.backup_path:
                backup_remote_path = exc.backup_path
            cleanup_failed = False
            if (
                temp_remote_path
                and not (
                    instruction.atomic
                    and instruction.upload_method == "sftp"
                )
            ):
                cleanup_failed = not delete_remote(conn, temp_remote_path)
            if backed_up:
                restore_backup(conn, backup_remote_path, remote_path)
            self.pool.release(conn)
            failure_meta = {
                "local_path": str(local_path),
                "remote_path": remote_path,
                "temp_remote_path": temp_remote_path,
                "backup_remote_path": backup_remote_path,
                "bytes_total": file_size,
                "bytes_transferred": bytes_transferred,
                "local_sha256": local_sha256,
                "atomic": instruction.atomic,
                "conflict_policy": instruction.conflict_policy,
                "upload_method": instruction.upload_method,
                "backed_up": backed_up,
                "cleanup_failed": cleanup_failed,
                "backup_restored": getattr(exc, "restored", False),
            }
            elapsed = time.time() - step_started_at
            safe_msg = redact_text(str(exc), instruction.redaction_patterns)
            self.audit_store.append_event(
                AuditEvent(
                    event_type="step_failed", actor=actor, target_alias=plan.target_alias,
                    plan_id=run.plan_id, run_id=run.id, step_id=step.id,
                    instruction_kind=instruction.kind, instruction_preview=preview,
                    risk_level=step.risk_level, elapsed_seconds=round(elapsed, 3),
                    error_type=type(exc).__name__, error_message=safe_msg,
                    metadata=failure_meta,
                )
            )
            return StepResult(step.id, instruction.kind, "failed", elapsed_seconds=round(elapsed, 3), error_message=safe_msg, metadata=failure_meta)


def _summarize(text: str, patterns: list[str] | None = None) -> dict[str, str | bool]:
    raw = text or ""
    digest = "sha256:" + hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
    redacted = redact_text(raw, patterns)
    truncated = len(redacted.encode("utf-8")) > EXCERPT_LIMIT
    if truncated:
        excerpt = redacted.encode("utf-8")[:EXCERPT_LIMIT].decode("utf-8", errors="ignore")
    else:
        excerpt = redacted
    return {"digest": digest, "excerpt": excerpt, "truncated": truncated}


@dataclass
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    elapsed_seconds: float


def exec_command_via_ssh(
    target: ConnectionTarget,
    command: str,
    *,
    timeout: int | None = None,
    workdir: str | None = None,
) -> CommandResult:
    if not command.strip():
        raise ValueError("command is required")
    if target.auth_type != "key" or not target.identity_file:
        raise ValueError("MCP execution currently requires key authentication")

    remote_command = command
    if workdir:
        remote_command = f"cd {shlex.quote(workdir)} && {command}"

    ssh_cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={min(max(timeout or 30, 1), 60)}",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-i",
        target.identity_file,
        "-p",
        str(target.port),
        f"{target.username}@{target.hostname}",
        remote_command,
    ]

    started = time.monotonic()
    try:
        completed = subprocess.run(
            ssh_cmd,
            text=True,
            capture_output=True,
            timeout=timeout or 120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"command timed out after {timeout or 120} seconds") from exc

    return CommandResult(
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        elapsed_seconds=round(time.monotonic() - started, 3),
    )
