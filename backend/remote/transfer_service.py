from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable

from backend.ssh.models import ConnectionTarget

from .audit_store import AuditStore
from .models import ExecutionPlan, PlanStep
from .plan_store import PlanStore
from .transfer_models import transfer_to_dict
from .transfer_store import TransferStore
from .transfer_worker import (
    MAX_RUNNING_TRANSFERS,
    MAX_RUNNING_TRANSFERS_PER_TARGET,
    UploadJob,
    TransferWorker,
)
from .upload_utils import (
    resolve_local_path,
    temp_path,
    validate_local_file,
    validate_remote_path,
)


POLL_AFTER_SECONDS = 30
TargetResolver = Callable[[str], ConnectionTarget]


class TransferService:
    def __init__(
        self,
        *,
        plan_store: PlanStore,
        audit_store: AuditStore,
        transfer_store: TransferStore,
        pool: object | None,
        target_resolver: TargetResolver,
    ) -> None:
        self.plan_store = plan_store
        self.audit_store = audit_store
        self.transfer_store = transfer_store
        self.target_resolver = target_resolver
        self.worker = TransferWorker(
            transfer_store=transfer_store,
            audit_store=audit_store,
            pool=pool,
            plan_store=plan_store,
        )

    def start_transfer(
        self,
        *,
        plan_id: str,
        plan_hash: str | None,
        step_id: str,
        actor: str,
    ) -> dict[str, object]:
        plan = self._load_plan(plan_id)
        self._validate_plan(plan, plan_hash)
        step = self._find_step(plan, step_id)
        instruction = step.instruction
        if instruction is None or instruction.kind != "sftp_put":
            raise ValueError("step instruction must be sftp_put")
        local_path = resolve_local_path(instruction.local_path or "")
        if local_path is None:
            raise ValueError("local_path is required")
        local_err = validate_local_file(local_path)
        if local_err:
            raise ValueError(local_err)
        remote_path = instruction.remote_path or ""
        remote_err = validate_remote_path(remote_path)
        if remote_err:
            raise ValueError(remote_err)
        bytes_total = local_path.stat().st_size
        actual_remote_path = remote_path
        temp_remote_path = (
            temp_path(remote_path) if instruction.atomic else actual_remote_path
        )
        record, error, existing = self.transfer_store.create_upload_if_allowed(
            max_total_active=MAX_RUNNING_TRANSFERS,
            max_active_per_target=MAX_RUNNING_TRANSFERS_PER_TARGET,
            target_alias=plan.target_alias,
            plan_id=plan.id,
            step_id=step.id,
            actor=actor,
            local_path=str(local_path),
            local_path_display=_display_path(local_path),
            remote_path=remote_path,
            actual_remote_path=actual_remote_path,
            temp_remote_path=temp_remote_path,
            conflict_policy=instruction.conflict_policy,
            atomic=instruction.atomic,
            verify=instruction.verify,
            bytes_total=bytes_total,
            upload_method=instruction.upload_method,
        )
        if existing is not None:
            return {
                "success": False,
                "error": "transfer_already_running",
                "transfer_id": existing.transfer_id,
                "status": existing.status,
                "message": "an active transfer already exists for this plan step",
            }
        if record is None:
            return {
                "success": False,
                "error": error,
                "message": error or "too many transfers",
            }
        self._save_plan_metadata(
            plan,
            active_transfer_id=record.transfer_id,
            active_transfer_step_id=step.id,
            last_transfer_status=record.status,
        )
        job = UploadJob(
            transfer_id=record.transfer_id,
            target=self.target_resolver(plan.target_alias),
            instruction=instruction,
            step=step,
            actor=actor,
            target_alias=plan.target_alias,
            plan_id=plan.id,
        )
        self.worker.submit_upload(job)
        refreshed = self.transfer_store.get(record.transfer_id) or record
        return {
            "success": True,
            "transfer_id": refreshed.transfer_id,
            "status": refreshed.status,
            "target_alias": refreshed.target_alias,
            "local_path_display": refreshed.local_path_display,
            "remote_path": refreshed.remote_path,
            "bytes_total": refreshed.bytes_total,
            "conflict_policy": refreshed.conflict_policy,
            "upload_method": refreshed.upload_method,
            "poll_after_seconds": POLL_AFTER_SECONDS,
        }

    def get_transfer(self, *, transfer_id: str) -> dict[str, object]:
        record = self.transfer_store.get(transfer_id)
        if record is None:
            raise KeyError(f"Transfer '{transfer_id}' not found")
        return {"success": True, "transfer": transfer_to_dict(record)}

    def cancel_transfer(
        self,
        *,
        transfer_id: str,
        reason: str | None,
        actor: str,
    ) -> dict[str, object]:
        current = self.transfer_store.get(transfer_id)
        if current is None:
            raise KeyError(f"Transfer '{transfer_id}' not found")
        if current.status in {"verifying", "renaming"}:
            return {
                "success": False,
                "transfer_id": current.transfer_id,
                "status": current.status,
                "message": "cannot_cancel",
                "actor": actor,
            }
        record = self.transfer_store.request_cancel(transfer_id, reason)
        if record.status == "cancel_requested":
            self.worker.cancel_transfer(transfer_id)
            message = "cancel requested"
        else:
            message = f"transfer is already {record.status}"
        return {
            "success": record.status == "cancel_requested",
            "transfer_id": record.transfer_id,
            "status": record.status,
            "message": message,
            "actor": actor,
        }

    def list_transfers(
        self,
        *,
        target_alias: str | None,
        status: str | None,
        limit: int,
    ) -> dict[str, object]:
        records = self.transfer_store.list(
            target_alias=target_alias,
            status=status,
            limit=limit,
        )
        return {
            "success": True,
            "transfers": [transfer_to_dict(record) for record in records],
        }

    def _load_plan(self, plan_id: str) -> ExecutionPlan:
        plan = self.plan_store.get(plan_id)
        if plan is None:
            raise KeyError(f"Plan '{plan_id}' not found")
        return plan

    def _validate_plan(self, plan: ExecutionPlan, plan_hash: str | None) -> None:
        if plan_hash and plan_hash != plan.plan_hash:
            raise ValueError("Plan hash mismatch")
        if plan.expires_at is not None and plan.expires_at < time.time():
            expired = replace(plan, status="expired")
            self.plan_store.save(expired)
            raise ValueError(f"Plan '{plan.id}' has expired")
        if plan.status != "approved":
            raise ValueError(
                f"Plan '{plan.id}' must be approved before starting transfer"
            )

    def _find_step(self, plan: ExecutionPlan, step_id: str) -> PlanStep:
        for step in plan.steps:
            if step.id == step_id:
                return step
        raise KeyError(f"Step '{step_id}' not found")

    def _save_plan_metadata(self, plan: ExecutionPlan, **metadata: object) -> None:
        self.plan_store.save(replace(plan, metadata={**plan.metadata, **metadata}))


def _display_path(path: Path) -> str:
    cwd = Path.cwd().resolve()
    try:
        return "./" + str(path.relative_to(cwd))
    except ValueError:
        home = Path.home().resolve()
        try:
            return "~/" + str(path.relative_to(home))
        except ValueError:
            return os.path.basename(path)
