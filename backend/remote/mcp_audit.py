from __future__ import annotations

import time
from typing import Any

from .models import AuditEvent
from .policy import redact_text


SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "passphrase",
    "token",
    "secret",
    "api_key",
    "apikey",
    "private_key",
    "privatekey",
)
MAX_TEXT_LENGTH = 4000
MAX_LIST_ITEMS = 50
MAX_DICT_ITEMS = 100


def append_mcp_started(
    audit_store: Any,
    *,
    request_id: object,
    tool_name: str,
    arguments: dict[str, Any],
    actor: str = "mcp-client",
) -> float:
    started = time.monotonic()
    audit_store.append_event(
        AuditEvent(
            event_type="mcp_call_started",
            actor=actor,
            instruction_preview=tool_name,
            metadata={
                "request_id": request_id,
                "tool_name": tool_name,
                "arguments": sanitize_for_audit(arguments),
            },
        )
    )
    return started


def append_mcp_finished(
    audit_store: Any,
    *,
    request_id: object,
    tool_name: str,
    result: dict[str, Any],
    started: float,
    actor: str = "mcp-client",
) -> None:
    audit_store.append_event(
        AuditEvent(
            event_type="mcp_call_finished",
            actor=actor,
            instruction_preview=tool_name,
            decision="success" if bool(result.get("success", True)) else "error",
            elapsed_seconds=round(time.monotonic() - started, 3),
            metadata={
                "request_id": request_id,
                "tool_name": tool_name,
                "result": sanitize_for_audit(result),
            },
        )
    )


def append_mcp_failed(
    audit_store: Any,
    *,
    request_id: object,
    tool_name: str,
    error: Exception,
    started: float,
    actor: str = "mcp-client",
) -> None:
    audit_store.append_event(
        AuditEvent(
            event_type="mcp_call_failed",
            actor=actor,
            instruction_preview=tool_name,
            decision="error",
            elapsed_seconds=round(time.monotonic() - started, 3),
            error_type=type(error).__name__,
            error_message=str(error),
            metadata={
                "request_id": request_id,
                "tool_name": tool_name,
            },
        )
    )


def sanitize_for_audit(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_DICT_ITEMS:
                sanitized["__truncated__"] = True
                break
            key_text = str(key)
            if _is_sensitive_key(key_text):
                sanitized[key_text] = "[REDACTED]"
            else:
                sanitized[key_text] = sanitize_for_audit(item)
        return sanitized
    if isinstance(value, list):
        items = [sanitize_for_audit(item) for item in value[:MAX_LIST_ITEMS]]
        if len(value) > MAX_LIST_ITEMS:
            items.append({"__truncated__": True, "omitted_items": len(value) - MAX_LIST_ITEMS})
        return items
    if isinstance(value, str):
        redacted = redact_text(value)
        if len(redacted) > MAX_TEXT_LENGTH:
            return redacted[:MAX_TEXT_LENGTH] + "...[TRUNCATED]"
        return redacted
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)
