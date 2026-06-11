from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


PlanStatus = Literal[
    "draft",
    "pending_approval",
    "approved",
    "rejected",
    "expired",
    "executed",
]
RiskLevel = Literal["low", "medium", "high"]
UploadMethod = Literal["sftp", "scp"]
InstructionKind = Literal[
    "shell",
    "sftp_put",
    "sftp_get",
    "read_file",
    "write_file",
    "interactive",
]
AuditEventType = Literal[
    "mcp_call_started",
    "mcp_call_finished",
    "mcp_call_failed",
    "plan_created",
    "approval_requested",
    "approval_granted",
    "approval_rejected",
    "plan_expired",
    "run_started",
    "step_started",
    "step_finished",
    "step_failed",
    "instruction_blocked",
    "run_finished",
    "run_failed",
]
RunStatus = Literal["running", "succeeded", "failed", "cancelled", "timed_out"]
PolicyDecision = Literal["allow", "require_approval", "block"]


@dataclass(frozen=True)
class Instruction:
    kind: InstructionKind
    command: str | None = None
    workdir: str = ""
    timeout_seconds: int = 60
    stdin: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    local_path: str | None = None
    remote_path: str | None = None
    content: str | None = None
    create_backup: bool = True
    backup: bool = False
    atomic: bool = True
    verify: bool = True
    conflict_policy: str = "fail"
    backup_suffix: str = ".bak.{timestamp}.{sha256_8}"
    mode: str | None = None
    upload_method: UploadMethod = "sftp"
    redaction_patterns: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InstructionPreview:
    kind: InstructionKind
    display: str
    risk_level: RiskLevel
    redacted: bool = False


@dataclass(frozen=True)
class PlanStep:
    id: str = field(default_factory=lambda: "step-" + uuid.uuid4().hex[:12])
    title: str = ""
    description: str = ""
    instruction: Instruction | None = None
    expected_effect: str = ""
    rollback_hint: str | None = None
    risk_level: RiskLevel = "low"


@dataclass(frozen=True)
class ExecutionPlan:
    id: str = field(default_factory=lambda: "plan-" + uuid.uuid4().hex[:12])
    target_alias: str = ""
    goal: str = ""
    summary: str = ""
    steps: list[PlanStep] = field(default_factory=list)
    risk_level: RiskLevel = "low"
    status: PlanStatus = "draft"
    requires_approval: bool = False
    created_by: str = "system"
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    approved_by: str | None = None
    approved_at: float | None = None
    rejected_by: str | None = None
    rejected_at: float | None = None
    executed_at: float | None = None

    @property
    def plan_hash(self) -> str:
        return stable_plan_hash(self)


def stable_plan_hash(plan: ExecutionPlan) -> str:
    """Hash only the user-approved operation, not runtime metadata."""
    metadata = {
        key: value
        for key, value in plan.metadata.items()
        if not str(key).startswith("active_transfer_")
        and str(key) not in {"last_transfer_status"}
    }
    payload = {
        "target_alias": plan.target_alias,
        "goal": plan.goal,
        "summary": plan.summary,
        "steps": [_step_hash_payload(step) for step in plan.steps],
        "risk_level": plan.risk_level,
        "requires_approval": plan.requires_approval,
        "created_by": plan.created_by,
        "created_at": plan.created_at,
        "expires_at": plan.expires_at,
        "metadata": metadata,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _step_hash_payload(step: PlanStep) -> dict[str, Any]:
    payload = asdict(step)
    instruction = payload.get("instruction")
    if isinstance(instruction, dict) and instruction.get("upload_method") == "sftp":
        instruction.pop("upload_method", None)
    return payload


@dataclass(frozen=True)
class AuditEvent:
    id: str = field(default_factory=lambda: "evt-" + uuid.uuid4().hex[:12])
    event_type: AuditEventType = "run_started"
    timestamp: float = field(default_factory=time.time)
    actor: str = "system"
    target_alias: str = ""
    plan_id: str | None = None
    run_id: str | None = None
    step_id: str | None = None
    instruction_kind: InstructionKind | None = None
    instruction_preview: str | None = None
    risk_level: RiskLevel | None = None
    decision: str | None = None
    exit_code: int | None = None
    elapsed_seconds: float | None = None
    stdout_digest: str | None = None
    stderr_digest: str | None = None
    stdout_excerpt: str | None = None
    stderr_excerpt: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StepResult:
    step_id: str
    instruction_kind: InstructionKind
    status: RunStatus
    exit_code: int | None = None
    elapsed_seconds: float | None = None
    stdout_digest: str | None = None
    stderr_digest: str | None = None
    stdout_excerpt: str | None = None
    stderr_excerpt: str | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionRun:
    id: str = field(default_factory=lambda: "run-" + uuid.uuid4().hex[:12])
    plan_id: str | None = None
    target_alias: str = ""
    status: RunStatus = "running"
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    current_step_id: str | None = None
    step_results: list[StepResult] = field(default_factory=list)


@dataclass(frozen=True)
class PolicyResult:
    decision: PolicyDecision
    risk_level: RiskLevel
    reason: str
    matched_rule: str | None = None


def instruction_from_dict(data: dict[str, Any]) -> Instruction:
    kind = data.get("kind")
    if kind not in {"shell", "sftp_put", "sftp_get", "read_file", "write_file", "interactive"}:
        raise ValueError("instruction.kind is invalid")
    timeout = int(data.get("timeout_seconds", 60))
    if timeout < 1:
        raise ValueError("instruction.timeout_seconds must be positive")
    conflict_policy = str(data.get("conflict_policy", "fail"))
    if conflict_policy not in {"fail", "overwrite", "backup_then_overwrite", "rename_new"}:
        raise ValueError(f"invalid conflict_policy: {conflict_policy}")
    backup = _parse_bool(data.get("backup"), False)
    if conflict_policy == "backup_then_overwrite" and not backup:
        raise ValueError("backup must be true when conflict_policy is backup_then_overwrite")
    mode_raw = data.get("mode")
    mode = str(mode_raw) if mode_raw is not None and str(mode_raw).strip() else None
    if mode is not None:
        mode = _validate_mode(mode)
    upload_method = str(data.get("upload_method", "sftp") or "sftp")
    if upload_method not in {"sftp", "scp"}:
        raise ValueError(f"invalid upload_method: {upload_method}")
    return Instruction(
        kind=kind,
        command=_optional_str(data.get("command")),
        workdir=str(data.get("workdir", "") or ""),
        timeout_seconds=timeout,
        stdin=_optional_str(data.get("stdin")),
        env=_string_dict(data.get("env", {})),
        local_path=_optional_str(data.get("local_path")),
        remote_path=_optional_str(data.get("remote_path")),
        content=_optional_str(data.get("content")),
        create_backup=_parse_bool(data.get("create_backup"), True),
        backup=backup,
        atomic=_parse_bool(data.get("atomic"), True),
        verify=_parse_bool(data.get("verify"), True),
        conflict_policy=conflict_policy,
        backup_suffix=str(data.get("backup_suffix", ".bak.{timestamp}.{sha256_8}")),
        mode=mode,
        upload_method=upload_method,  # type: ignore[arg-type]
        redaction_patterns=[str(x) for x in data.get("redaction_patterns", []) if str(x)],
        metadata=data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {},
    )


def plan_to_dict(plan: ExecutionPlan) -> dict[str, Any]:
    data = asdict(plan)
    data["plan_hash"] = plan.plan_hash
    return data


def plan_from_dict(data: dict[str, Any]) -> ExecutionPlan:
    steps = []
    for raw_step in data.get("steps", []):
        raw_instruction = raw_step.get("instruction")
        instruction = instruction_from_dict(raw_instruction) if raw_instruction else None
        steps.append(
            PlanStep(
                id=raw_step.get("id", ""),
                title=raw_step.get("title", ""),
                description=raw_step.get("description", ""),
                instruction=instruction,
                expected_effect=raw_step.get("expected_effect", ""),
                rollback_hint=raw_step.get("rollback_hint"),
                risk_level=raw_step.get("risk_level", "low"),
            )
        )
    return ExecutionPlan(
        id=data.get("id", ""),
        target_alias=data.get("target_alias", ""),
        goal=data.get("goal", ""),
        summary=data.get("summary", ""),
        steps=steps,
        risk_level=data.get("risk_level", "low"),
        status=data.get("status", "draft"),
        requires_approval=bool(data.get("requires_approval", False)),
        created_by=data.get("created_by", "system"),
        created_at=float(data.get("created_at", time.time())),
        expires_at=data.get("expires_at"),
        metadata=data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {},
        approved_by=data.get("approved_by"),
        approved_at=data.get("approved_at"),
        rejected_by=data.get("rejected_by"),
        rejected_at=data.get("rejected_at"),
        executed_at=data.get("executed_at"),
    )


def audit_event_to_dict(event: AuditEvent) -> dict[str, Any]:
    return asdict(event)


def audit_event_from_dict(data: dict[str, Any]) -> AuditEvent:
    return AuditEvent(**data)


def run_to_dict(run: ExecutionRun) -> dict[str, Any]:
    return asdict(run)


def _parse_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        s = value.strip().lower()
        if s in {"true", "1", "yes", "on"}:
            return True
        if s in {"false", "0", "no", "off", ""}:
            return False
        raise ValueError(f"invalid boolean value: {value!r}")
    return bool(value)


def _validate_mode(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("0o") or raw.startswith("0O"):
        raise ValueError("mode must not use 0o prefix; use octal digits only, e.g. 644")
    try:
        val = int(raw, 8)
    except ValueError:
        raise ValueError(f"invalid mode: {raw!r}")
    if val < 0:
        raise ValueError(f"mode must not be negative: {raw!r}")
    if val > 0o777:
        raise ValueError(f"mode out of range (000-777): {raw!r}")
    return raw


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _string_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items()}
