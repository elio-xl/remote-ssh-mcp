from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.paths import data_dir

from .models import AuditEvent, audit_event_from_dict, audit_event_to_dict
from .policy import redact_text


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = data_dir()
DEFAULT_AUDIT_PATH = DEFAULT_DATA_DIR / "audit.jsonl"


class AuditStore:
    def __init__(self, path: Path = DEFAULT_AUDIT_PATH) -> None:
        self.path = path

    def append_event(self, event: AuditEvent) -> AuditEvent:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        safe = _redact_audit_value(audit_event_to_dict(event))
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(safe, ensure_ascii=False, separators=(",", ":")) + "\n")
        return audit_event_from_dict(safe)

    def list_events(
        self,
        *,
        target_alias: str | None = None,
        plan_id: str | None = None,
        run_id: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[AuditEvent]:
        if not self.path.exists():
            return []
        events: list[AuditEvent] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = audit_event_from_dict(json.loads(line))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if target_alias and event.target_alias != target_alias:
                    continue
                if plan_id and event.plan_id != plan_id:
                    continue
                if run_id and event.run_id != run_id:
                    continue
                if event_type and event.event_type != event_type:
                    continue
                events.append(audit_event_from_dict(_redact_audit_value(audit_event_to_dict(event))))
        return events[-max(1, limit) :]


_default_store = AuditStore()


def append_event(event: AuditEvent) -> AuditEvent:
    return _default_store.append_event(event)


def list_events(**kwargs: object) -> list[AuditEvent]:
    return _default_store.list_events(**kwargs)  # type: ignore[arg-type]


def _redact_audit_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_audit_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_audit_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
