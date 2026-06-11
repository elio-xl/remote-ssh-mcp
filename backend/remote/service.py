from __future__ import annotations

import time
from dataclasses import asdict, replace
from typing import Any

from backend.ssh.models import ConnectionTarget
from backend.ssh_config_service import get_entry, list_entries

from .audit_store import AuditStore
from .models import (
    AuditEvent,
    ExecutionPlan,
    Instruction,
    PlanStep,
    audit_event_to_dict,
    instruction_from_dict,
    plan_to_dict,
    run_to_dict,
)
from .plan_store import PlanStore
from .policy import classify_instruction, policy_to_dict, preview_instruction, redact_text
from .transfer_service import TransferService
from .transfer_store import TransferStore
from .upload_utils import preview_remote_state


RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
DEFAULT_PLAN_TTL_SECONDS = 24 * 60 * 60


class RemoteApplicationService:
    def __init__(
        self,
        *,
        plan_store: PlanStore | None = None,
        audit_store: AuditStore | None = None,
        pool: Any | None = None,
        transfer_store: TransferStore | None = None,
    ) -> None:
        self.plan_store = plan_store or PlanStore()
        self.audit_store = audit_store or AuditStore()
        self.transfer_store = transfer_store or TransferStore()
        self.pool = pool
        self.runner = None
        self.transfer_service = TransferService(
            plan_store=self.plan_store,
            audit_store=self.audit_store,
            transfer_store=self.transfer_store,
            pool=self.pool,
            target_resolver=self._resolve_target,
        )

    def list_targets(self) -> dict[str, object]:
        targets = []
        for entry in list_entries():
            targets.append(
                {
                    "alias": entry.host,
                    "host_display": _mask_host(entry.hostname),
                    "username": entry.user,
                    "auth_type": entry.type,
                    "has_jump_host": False,
                }
            )
        return {"success": True, "targets": targets}

    def preview_instruction(self, *, target_alias: str, instruction_data: dict[str, object]) -> dict[str, object]:
        self._require_target(target_alias)
        instruction = instruction_from_dict(instruction_data)
        policy = classify_instruction(instruction)
        preview = preview_instruction(instruction)
        return {
            "success": True,
            "target_alias": target_alias,
            "instruction_preview": asdict(preview),
            "policy": policy_to_dict(policy),
        }

    def create_plan(
        self,
        *,
        target_alias: str,
        goal: str,
        instructions_data: list[dict[str, object]],
        created_by: str = "mcp-client",
        ttl_seconds: int = DEFAULT_PLAN_TTL_SECONDS,
    ) -> dict[str, object]:
        self._require_target(target_alias)
        if not instructions_data:
            raise ValueError("instructions is required")
        steps: list[PlanStep] = []
        requires_approval = False
        highest = "low"
        previews: list[str] = []
        for idx, raw_instruction in enumerate(instructions_data, start=1):
            instruction = instruction_from_dict(raw_instruction)
            policy = classify_instruction(instruction)
            preview = preview_instruction(instruction)
            if policy.decision == "block":
                self.audit_store.append_event(
                    AuditEvent(
                        event_type="instruction_blocked",
                        actor=created_by,
                        target_alias=target_alias,
                        instruction_kind=instruction.kind,
                        instruction_preview=preview.display,
                        risk_level=policy.risk_level,
                        decision=policy.decision,
                        error_message=policy.reason,
                    )
                )
                raise ValueError(f"instruction blocked: {policy.reason}")
            requires_approval = requires_approval or policy.decision == "require_approval"
            highest = _max_risk(highest, policy.risk_level)
            previews.append(preview.display)
            steps.append(
                PlanStep(
                    title=f"Step {idx}: {instruction.kind}",
                    description=preview.display,
                    instruction=instruction,
                    expected_effect=_expected_effect(instruction, policy.risk_level),
                    rollback_hint=_rollback_hint(instruction, policy.risk_level),
                    risk_level=policy.risk_level,
                )
            )
        plan = ExecutionPlan(
            target_alias=target_alias,
            goal=goal.strip() or "remote operation",
            summary=_summary(goal, previews),
            steps=steps,
            risk_level=highest,  # type: ignore[arg-type]
            status="pending_approval" if requires_approval else "draft",
            requires_approval=requires_approval,
            created_by=created_by,
            expires_at=time.time() + max(60, int(ttl_seconds)),
        )
        remote_conflicts = []
        if self.pool is not None:
            remote_conflicts = preview_remote_state(
                self.pool,
                self._resolve_target(target_alias),
                steps,
            )
        if remote_conflicts:
            plan = replace(plan, metadata={**plan.metadata, "remote_conflicts": remote_conflicts})
        self.plan_store.save(plan)
        self.audit_store.append_event(
            AuditEvent(
                event_type="plan_created",
                actor=created_by,
                target_alias=target_alias,
                plan_id=plan.id,
                risk_level=plan.risk_level,
                instruction_preview="; ".join(previews),
                decision="require_approval" if requires_approval else "allow",
                metadata={"plan_hash": plan.plan_hash},
            )
        )
        if requires_approval:
            self.audit_store.append_event(
                AuditEvent(
                    event_type="approval_requested",
                    actor=created_by,
                    target_alias=target_alias,
                    plan_id=plan.id,
                    risk_level=plan.risk_level,
                    instruction_preview="; ".join(previews),
                    metadata={"plan_hash": plan.plan_hash},
                )
            )
        return {"success": True, "plan": self._plan_response(plan)}

    def list_plans(
        self,
        *,
        target_alias: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> dict[str, object]:
        plans = self.plan_store.list_plans(target_alias=target_alias, status=status, limit=limit)  # type: ignore[arg-type]
        return {"success": True, "plans": [self._plan_response(plan) for plan in plans]}

    def get_plan(self, *, plan_id: str) -> dict[str, object]:
        plan = self.plan_store.get(plan_id)
        if plan is None:
            raise KeyError(f"Plan '{plan_id}' not found")
        return {"success": True, "plan": self._plan_response(plan)}

    def approve_plan(
        self,
        *,
        plan_id: str,
        plan_hash: str | None = None,
        approved_by: str = "user",
        comment: str | None = None,
    ) -> dict[str, object]:
        plan = self._load_plan(plan_id)
        self._validate_hash(plan, plan_hash)
        self._ensure_not_expired(plan)
        if plan.status in {"rejected", "executed", "expired"}:
            raise ValueError(f"Plan '{plan_id}' cannot be approved from status {plan.status}")
        if plan.status not in {"draft", "pending_approval", "approved"}:
            raise ValueError(f"Plan '{plan_id}' is not approvable")
        updated = replace(
            plan,
            status="approved",
            approved_by=approved_by,
            approved_at=time.time(),
            metadata={**plan.metadata, **({"approval_comment": comment} if comment else {})},
        )
        self.plan_store.save(updated)
        self.audit_store.append_event(
            AuditEvent(
                event_type="approval_granted",
                actor=approved_by,
                target_alias=updated.target_alias,
                plan_id=updated.id,
                risk_level=updated.risk_level,
                decision="approved",
                metadata={"comment": redact_text(comment), "plan_hash": updated.plan_hash},
            )
        )
        return {
            "success": True,
            "plan_id": updated.id,
            "status": updated.status,
            "approved_by": approved_by,
            "approved_at": updated.approved_at,
            "plan": self._plan_response(updated),
        }

    def reject_plan(self, *, plan_id: str, rejected_by: str = "user", reason: str | None = None) -> dict[str, object]:
        plan = self._load_plan(plan_id)
        if plan.status in {"executed", "expired"}:
            raise ValueError(f"Plan '{plan_id}' cannot be rejected from status {plan.status}")
        updated = replace(
            plan,
            status="rejected",
            rejected_by=rejected_by,
            rejected_at=time.time(),
            metadata={**plan.metadata, **({"reject_reason": reason} if reason else {})},
        )
        self.plan_store.save(updated)
        self.audit_store.append_event(
            AuditEvent(
                event_type="approval_rejected",
                actor=rejected_by,
                target_alias=updated.target_alias,
                plan_id=updated.id,
                risk_level=updated.risk_level,
                decision="rejected",
                metadata={"reason": redact_text(reason)},
            )
        )
        return {"success": True, "plan_id": updated.id, "status": updated.status, "plan": self._plan_response(updated)}

    def execute_plan(self, *, plan_id: str, plan_hash: str | None = None, actor: str = "user") -> dict[str, object]:
        plan = self._load_plan(plan_id)
        self._validate_hash(plan, plan_hash)
        self._ensure_not_expired(plan)
        if plan.status == "executed":
            raise ValueError(f"Plan '{plan_id}' has already been executed")
        if plan.status in {"rejected", "expired"}:
            raise ValueError(f"Plan '{plan_id}' cannot be executed from status {plan.status}")
        if plan.requires_approval and plan.status != "approved":
            raise ValueError(f"Plan '{plan_id}' requires approval before execution")
        run = self._runner().run_plan(plan, actor=actor)
        if run.status == "succeeded":
            plan = replace(plan, status="executed", executed_at=time.time())
            self.plan_store.save(plan)
        return {"success": run.status == "succeeded", "plan_id": plan_id, "run": run_to_dict(run), "plan": self._plan_response(plan)}

    def run_instruction(
        self,
        *,
        target_alias: str,
        instruction_data: dict[str, object],
        actor: str = "mcp-client",
    ) -> dict[str, object]:
        self._require_target(target_alias)
        instruction = instruction_from_dict(instruction_data)
        policy = classify_instruction(instruction)
        preview = preview_instruction(instruction)
        if policy.decision == "block":
            self.audit_store.append_event(
                AuditEvent(
                    event_type="instruction_blocked",
                    actor=actor,
                    target_alias=target_alias,
                    instruction_kind=instruction.kind,
                    instruction_preview=preview.display,
                    risk_level=policy.risk_level,
                    decision=policy.decision,
                    error_message=policy.reason,
                )
            )
            return {"success": False, "blocked": True, "policy": policy_to_dict(policy), "message": policy.reason}
        if policy.decision == "require_approval":
            return {
                "success": False,
                "requires_plan": True,
                "policy": policy_to_dict(policy),
                "message": "Create and approve a plan before executing this instruction.",
            }
        run = self._runner().run_instruction(target_alias=target_alias, instruction=instruction, actor=actor)
        return {"success": run.status == "succeeded", "run": run_to_dict(run), "policy": policy_to_dict(policy)}

    def list_audit_events(
        self,
        *,
        target_alias: str | None = None,
        plan_id: str | None = None,
        run_id: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
    ) -> dict[str, object]:
        events = self.audit_store.list_events(
            target_alias=target_alias,
            plan_id=plan_id,
            run_id=run_id,
            event_type=event_type,
            limit=limit,
        )
        return {"success": True, "events": [audit_event_to_dict(event) for event in events]}

    def start_transfer(
        self,
        *,
        plan_id: str,
        plan_hash: str | None,
        step_id: str,
        actor: str,
    ) -> dict[str, object]:
        return self.transfer_service.start_transfer(
            plan_id=plan_id,
            plan_hash=plan_hash,
            step_id=step_id,
            actor=actor,
        )

    def get_transfer(self, *, transfer_id: str) -> dict[str, object]:
        return self.transfer_service.get_transfer(transfer_id=transfer_id)

    def cancel_transfer(
        self,
        *,
        transfer_id: str,
        reason: str | None,
        actor: str,
    ) -> dict[str, object]:
        return self.transfer_service.cancel_transfer(
            transfer_id=transfer_id,
            reason=reason,
            actor=actor,
        )

    def list_transfers(
        self,
        *,
        target_alias: str | None,
        status: str | None,
        limit: int,
    ) -> dict[str, object]:
        return self.transfer_service.list_transfers(
            target_alias=target_alias,
            status=status,
            limit=limit,
        )

    def capabilities(self) -> dict[str, object]:
        return {
            "success": True,
            "instruction_kinds": ["shell", "read_file", "write_file", "sftp_put", "sftp_get", "interactive"],
            "transfer_tools": [
                "remote_start_transfer",
                "remote_get_transfer",
                "remote_cancel_transfer",
                "remote_list_transfers",
            ],
            "direct_run_policy": {
                "supports_direct_low_risk": True,
                "requires_plan_for_medium_risk": True,
                "requires_plan_for_high_risk": True,
            },
            "limits": {
                "max_steps_per_plan": 20,
                "default_plan_ttl_seconds": DEFAULT_PLAN_TTL_SECONDS,
                "stdout_excerpt_bytes": 8192,
                "stderr_excerpt_bytes": 8192,
            },
        }

    def _plan_response(self, plan: ExecutionPlan) -> dict[str, object]:
        data = plan_to_dict(plan)
        for step, raw_step in zip(plan.steps, data.get("steps", [])):
            if step.instruction is not None:
                raw_step["instruction_preview"] = preview_instruction(step.instruction).display
        return data

    def _load_plan(self, plan_id: str) -> ExecutionPlan:
        plan = self.plan_store.get(plan_id)
        if plan is None:
            raise KeyError(f"Plan '{plan_id}' not found")
        return plan

    def _validate_hash(self, plan: ExecutionPlan, plan_hash: str | None) -> None:
        if plan_hash and plan_hash != plan.plan_hash:
            raise ValueError("Plan hash mismatch")

    def _ensure_not_expired(self, plan: ExecutionPlan) -> None:
        if plan.expires_at is not None and plan.expires_at < time.time():
            expired = replace(plan, status="expired")
            self.plan_store.save(expired)
            self.audit_store.append_event(
                AuditEvent(
                    event_type="plan_expired",
                    actor="system",
                    target_alias=plan.target_alias,
                    plan_id=plan.id,
                    risk_level=plan.risk_level,
                )
            )
            raise ValueError(f"Plan '{plan.id}' has expired")

    def _resolve_target(self, target_alias: str) -> ConnectionTarget:
        entry = self._require_target(target_alias)
        return ConnectionTarget(
            alias=entry.host,
            hostname=entry.hostname,
            port=entry.port,
            username=entry.user,
            auth_type=entry.type,
            identity_file=entry.IdentityFile or None,
            password=entry.password or None,
        )

    def _runner(self):
        if self.runner is None:
            from .runner import RemoteRunner

            self.runner = RemoteRunner(
                audit_store=self.audit_store,
                target_resolver=self._resolve_target,
                pool=self.pool,
            )
        return self.runner

    def _require_target(self, target_alias: str):
        entry = get_entry(target_alias)
        if entry is None:
            raise KeyError(f"Host '{target_alias}' 未找到")
        return entry


def _max_risk(left: str, right: str) -> str:
    return right if RISK_ORDER[right] > RISK_ORDER[left] else left


def _summary(goal: str, previews: list[str]) -> str:
    if goal.strip():
        return goal.strip()
    if len(previews) == 1:
        return previews[0]
    return f"Run {len(previews)} remote instructions"


def _expected_effect(instruction: Instruction, risk_level: str) -> str:
    if instruction.kind == "shell":
        if risk_level == "low":
            return "read-only command returns remote state information"
        return "command may change remote state or service runtime"
    return f"{instruction.kind} operation on remote target"


def _rollback_hint(instruction: Instruction, risk_level: str) -> str | None:
    if risk_level == "low":
        return None
    if instruction.kind == "shell":
        return "review command output and restore affected service or file from backup if needed"
    return "restore affected remote file from backup if needed"


def _mask_host(hostname: str) -> str:
    if not hostname:
        return ""
    parts = hostname.split(".")
    if len(parts) == 4 and all(part.isdigit() for part in parts):
        return f"{parts[0]}.{parts[1]}.*.*"
    if len(parts) > 2:
        return f"{parts[0]}.*.{parts[-1]}"
    if len(hostname) <= 2:
        return "*"
    return hostname[0] + "*" * (len(hostname) - 2) + hostname[-1]
