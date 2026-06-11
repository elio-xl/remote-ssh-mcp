from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


TransferStatus = Literal[
    "pending",
    "running",
    "verifying",
    "renaming",
    "succeeded",
    "failed",
    "cancel_requested",
    "cancelled",
    "timed_out",
    "conflict",
]
TransferDirection = Literal["upload", "download"]
UploadMethod = Literal["sftp", "scp"]

ACTIVE_TRANSFER_STATUSES: set[str] = {
    "pending",
    "running",
    "cancel_requested",
    "verifying",
    "renaming",
}
TERMINAL_TRANSFER_STATUSES: set[str] = {
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "conflict",
}


@dataclass
class TransferRecord:
    transfer_id: str = field(default_factory=lambda: "transfer-" + uuid.uuid4().hex[:12])
    direction: TransferDirection = "upload"
    status: TransferStatus = "pending"
    target_alias: str = ""
    plan_id: str | None = None
    run_id: str | None = None
    step_id: str | None = None
    actor: str = "system"
    local_path: str = ""
    local_path_display: str = ""
    remote_path: str = ""
    actual_remote_path: str = ""
    temp_remote_path: str = ""
    backup_remote_path: str = ""
    conflict_policy: str = "fail"
    upload_method: UploadMethod = "sftp"
    atomic: bool = True
    verify: bool = True
    bytes_total: int = 0
    bytes_transferred: int = 0
    percent: float = 0.0
    bytes_per_second: float | None = None
    eta_seconds: float | None = None
    local_sha256: str | None = None
    remote_sha256: str | None = None
    cancel_requested: bool = False
    started_at: float | None = None
    transfer_started_at: float | None = None
    transfer_finished_at: float | None = None
    finished_at: float | None = None
    elapsed_seconds: float | None = None
    error_type: str | None = None
    error_message: str | None = None
    cleanup_failed: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


def transfer_to_dict(record: TransferRecord, *, include_local_path: bool = False) -> dict[str, Any]:
    data = asdict(record)
    if not include_local_path:
        data.pop("local_path", None)
    return data


def transfer_from_dict(data: dict[str, Any]) -> TransferRecord:
    known = {field.name for field in TransferRecord.__dataclass_fields__.values()}
    values = {key: value for key, value in data.items() if key in known}
    return TransferRecord(**values)
