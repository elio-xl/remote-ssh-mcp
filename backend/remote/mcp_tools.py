from __future__ import annotations

from typing import Any


def get_mcp_tools() -> list[dict[str, Any]]:
    return [
        tool(
            "remote_list_targets",
            "List configured remote SSH targets without exposing credentials.",
            {},
        ),
        tool(
            "remote_get_capabilities",
            "Return supported instruction kinds and policy limits.",
            {},
        ),
        tool(
            "remote_preview_instruction",
            (
                "Preview an instruction and classify policy without creating "
                "a plan or executing it."
            ),
            {
                "target_alias": {"type": "string"},
                "instruction": {"type": "object"},
            },
            ["target_alias", "instruction"],
        ),
        tool(
            "remote_create_plan",
            "Create an approval plan from one or more instructions.",
            {
                "target_alias": {"type": "string"},
                "goal": {"type": "string"},
                "instructions": {"type": "array", "items": {"type": "object"}},
                "ttl_seconds": {"type": "integer"},
            },
            ["target_alias", "instructions"],
        ),
        tool(
            "remote_list_plans",
            "List stored remote operation plans.",
            {
                "target_alias": {"type": "string"},
                "status": {"type": "string"},
                "limit": {"type": "integer"},
            },
        ),
        tool(
            "remote_get_plan",
            "Get one plan by id.",
            {"plan_id": {"type": "string"}},
            ["plan_id"],
        ),
        tool(
            "remote_approve_plan",
            "Approve a plan before execution.",
            {
                "plan_id": {"type": "string"},
                "plan_hash": {"type": "string"},
                "comment": {"type": "string"},
            },
            ["plan_id"],
        ),
        tool(
            "remote_reject_plan",
            "Reject a pending plan.",
            {
                "plan_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            ["plan_id"],
        ),
        tool(
            "remote_execute_plan",
            "Execute an approved plan.",
            {
                "plan_id": {"type": "string"},
                "plan_hash": {"type": "string"},
            },
            ["plan_id"],
        ),
        tool(
            "remote_start_transfer",
            (
                "Start an approved sftp_put plan step as a background transfer. "
                "Returns immediately; use remote_get_transfer to poll progress."
            ),
            {
                "plan_id": {"type": "string"},
                "plan_hash": {"type": "string"},
                "step_id": {"type": "string"},
                "actor": {"type": "string"},
            },
            ["plan_id", "step_id"],
        ),
        tool(
            "remote_get_transfer",
            (
                "Get background transfer status, progress, speed, ETA, paths, "
                "and result metadata."
            ),
            {"transfer_id": {"type": "string"}},
            ["transfer_id"],
        ),
        tool(
            "remote_cancel_transfer",
            (
                "Request cancellation for a pending or running transfer. "
                "Do not use shell process kills for upload cancellation."
            ),
            {
                "transfer_id": {"type": "string"},
                "reason": {"type": "string"},
                "actor": {"type": "string"},
            },
            ["transfer_id"],
        ),
        tool(
            "remote_list_transfers",
            (
                "List recent background transfers with optional target_alias/status "
                "filters."
            ),
            {
                "target_alias": {"type": "string"},
                "status": {"type": "string"},
                "limit": {"type": "integer"},
            },
        ),
        tool(
            "remote_run_instruction",
            "Run a single low-risk instruction directly.",
            {
                "target_alias": {"type": "string"},
                "instruction": {"type": "object"},
            },
            ["target_alias", "instruction"],
        ),
        tool(
            "remote_list_audit_events",
            "List audit events with optional filters.",
            {
                "limit": {"type": "integer"},
                "plan_id": {"type": "string"},
                "run_id": {"type": "string"},
                "target_alias": {"type": "string"},
                "event_type": {"type": "string"},
            },
        ),
        tool(
            "ssh_list_plans",
            "Compatibility alias for remote_list_plans.",
            {"limit": {"type": "integer"}},
        ),
        tool(
            "ssh_get_plan",
            "Compatibility alias for remote_get_plan.",
            {"plan_id": {"type": "string"}},
            ["plan_id"],
        ),
        tool(
            "ssh_approve_plan",
            "Compatibility alias for remote_approve_plan.",
            {
                "plan_id": {"type": "string"},
                "approval_note": {"type": "string"},
            },
            ["plan_id"],
        ),
        tool(
            "ssh_reject_plan",
            "Compatibility alias for remote_reject_plan.",
            {
                "plan_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            ["plan_id"],
        ),
        tool(
            "ssh_execute_plan",
            "Compatibility alias for remote_execute_plan.",
            {"plan_id": {"type": "string"}},
            ["plan_id"],
        ),
        tool(
            "ssh_read_audit_log",
            "Compatibility alias for remote_list_audit_events.",
            {
                "limit": {"type": "integer"},
                "event_filter": {"type": "string"},
            },
        ),
    ]


def tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": True,
        },
    }
