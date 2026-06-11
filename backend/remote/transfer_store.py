from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from threading import Lock
from typing import Any

from backend.paths import data_dir

from .transfer_models import (
    ACTIVE_TRANSFER_STATUSES,
    TERMINAL_TRANSFER_STATUSES,
    TransferRecord,
    TransferStatus,
    transfer_from_dict,
    transfer_to_dict,
)


DEFAULT_TRANSFER_PATH = data_dir() / "transfers.json"
PERSIST_INTERVAL_SECONDS = 2.0
PERSIST_INTERVAL_BYTES = 16 * 1024 * 1024
CANCEL_REQUEST_GRACE_SECONDS = 60.0
PENDING_STALE_SECONDS = 60.0
RUNNING_STALE_SECONDS = 5 * 60.0
FINALIZING_STALE_SECONDS = 15 * 60.0


class TransferStore:
    def __init__(self, path: Path = DEFAULT_TRANSFER_PATH) -> None:
        self.path = path
        self._lock = Lock()
        self._records: dict[str, TransferRecord] = self._read_all()
        self._last_persist_at: dict[str, float] = {}
        self._last_persist_bytes: dict[str, int] = {}
        if self._mark_stale_active_records():
            self._persist_locked()

    def create_upload(
        self,
        *,
        target_alias: str,
        plan_id: str,
        step_id: str,
        actor: str,
        local_path: str,
        local_path_display: str,
        remote_path: str,
        actual_remote_path: str,
        temp_remote_path: str,
        conflict_policy: str,
        atomic: bool,
        verify: bool,
        bytes_total: int,
        upload_method: str = "sftp",
    ) -> TransferRecord:
        now = time.time()
        record = TransferRecord(
            target_alias=target_alias,
            plan_id=plan_id,
            step_id=step_id,
            actor=actor,
            local_path=local_path,
            local_path_display=local_path_display,
            remote_path=remote_path,
            actual_remote_path=actual_remote_path,
            temp_remote_path=temp_remote_path,
            conflict_policy=conflict_policy,
            upload_method=upload_method,  # type: ignore[arg-type]
            atomic=atomic,
            verify=verify,
            bytes_total=bytes_total,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._records[record.transfer_id] = record
            self._persist_locked()
        return record

    def create_upload_if_allowed(
        self,
        *,
        max_total_active: int,
        max_active_per_target: int,
        target_alias: str,
        plan_id: str,
        step_id: str,
        actor: str,
        local_path: str,
        local_path_display: str,
        remote_path: str,
        actual_remote_path: str,
        temp_remote_path: str,
        conflict_policy: str,
        atomic: bool,
        verify: bool,
        bytes_total: int,
        upload_method: str = "sftp",
    ) -> tuple[TransferRecord | None, str | None, TransferRecord | None]:
        now = time.time()
        with self._lock:
            if self._mark_stale_active_records_locked(now):
                self._persist_locked()
            for record in self._records.values():
                if (
                    record.plan_id == plan_id
                    and record.step_id == step_id
                    and record.status in ACTIVE_TRANSFER_STATUSES
                ):
                    return None, "transfer_already_running", replace(record)
            active = [
                record
                for record in self._records.values()
                if record.status in ACTIVE_TRANSFER_STATUSES
            ]
            if len(active) >= max_total_active:
                return None, "too_many_transfers", None
            active_for_target = sum(
                1 for record in active if record.target_alias == target_alias
            )
            if active_for_target >= max_active_per_target:
                return None, "too_many_transfers_for_target", None

            record = TransferRecord(
                target_alias=target_alias,
                plan_id=plan_id,
                step_id=step_id,
                actor=actor,
                local_path=local_path,
                local_path_display=local_path_display,
                remote_path=remote_path,
                actual_remote_path=actual_remote_path,
                temp_remote_path=temp_remote_path,
                conflict_policy=conflict_policy,
                upload_method=upload_method,  # type: ignore[arg-type]
                atomic=atomic,
                verify=verify,
                bytes_total=bytes_total,
                created_at=now,
                updated_at=now,
            )
            self._records[record.transfer_id] = record
            self._persist_locked()
            return replace(record), None, None

    def get(self, transfer_id: str) -> TransferRecord | None:
        with self._lock:
            record = self._records.get(transfer_id)
            return replace(record) if record else None

    def list(
        self,
        *,
        target_alias: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[TransferRecord]:
        with self._lock:
            records = list(self._records.values())
        if target_alias:
            records = [
                record for record in records if record.target_alias == target_alias
            ]
        if status:
            records = [record for record in records if record.status == status]
        records.sort(key=lambda record: record.created_at, reverse=True)
        return [replace(record) for record in records[: max(1, limit)]]

    def find_active_for_step(
        self,
        *,
        plan_id: str,
        step_id: str,
    ) -> TransferRecord | None:
        with self._lock:
            for record in self._records.values():
                if (
                    record.plan_id == plan_id
                    and record.step_id == step_id
                    and record.status in ACTIVE_TRANSFER_STATUSES
                ):
                    return replace(record)
        return None

    def active_counts(self) -> tuple[int, dict[str, int]]:
        with self._lock:
            if self._mark_stale_active_records_locked(time.time()):
                self._persist_locked()
            active = [
                record
                for record in self._records.values()
                if record.status in ACTIVE_TRANSFER_STATUSES
            ]
        by_target: dict[str, int] = {}
        for record in active:
            by_target[record.target_alias] = by_target.get(record.target_alias, 0) + 1
        return len(active), by_target

    def update_progress(
        self,
        transfer_id: str,
        transferred: int,
        total: int,
    ) -> TransferRecord:
        now = time.time()
        with self._lock:
            record = self._require_locked(transfer_id)
            total = max(total, record.bytes_total, 0)
            percent = round((transferred / total) * 100, 2) if total > 0 else 0.0
            started = record.transfer_started_at or record.started_at or now
            elapsed = max(0.001, now - started)
            rate = transferred / elapsed if transferred > 0 else None
            remaining = max(total - transferred, 0)
            eta = remaining / rate if rate else None
            updated = replace(
                record,
                bytes_total=total,
                bytes_transferred=max(transferred, record.bytes_transferred),
                percent=percent,
                bytes_per_second=round(rate, 2) if rate else None,
                eta_seconds=round(eta, 1) if eta is not None else None,
                updated_at=now,
            )
            self._records[transfer_id] = updated
            self._persist_progress_if_needed_locked(updated)
            return replace(updated)

    def mark_status(
        self,
        transfer_id: str,
        status: TransferStatus,
        **updates: Any,
    ) -> TransferRecord:
        now = time.time()
        with self._lock:
            record = self._require_locked(transfer_id)
            if status == "running" and record.started_at is None:
                updates.setdefault("started_at", now)
                updates.setdefault("transfer_started_at", now)
            updated = replace(record, status=status, updated_at=now, **updates)
            self._records[transfer_id] = updated
            self._persist_locked()
            return replace(updated)

    def mark_succeeded(self, transfer_id: str, **updates: Any) -> TransferRecord:
        now = time.time()
        with self._lock:
            record = self._require_locked(transfer_id)
            started = record.started_at or record.created_at
            updated = replace(
                record,
                status="succeeded",
                bytes_transferred=max(record.bytes_transferred, record.bytes_total),
                percent=100.0 if record.bytes_total else record.percent,
                finished_at=now,
                elapsed_seconds=round(now - started, 3),
                updated_at=now,
                **updates,
            )
            self._records[transfer_id] = updated
            self._persist_locked()
            return replace(updated)

    def mark_failed(
        self,
        transfer_id: str,
        *,
        status: TransferStatus = "failed",
        error_type: str,
        error_message: str,
        cleanup_failed: bool = False,
        **updates: Any,
    ) -> TransferRecord:
        now = time.time()
        with self._lock:
            record = self._require_locked(transfer_id)
            started = record.started_at or record.created_at
            updated = replace(
                record,
                status=status,
                error_type=error_type,
                error_message=error_message,
                cleanup_failed=cleanup_failed,
                finished_at=now,
                elapsed_seconds=round(now - started, 3),
                updated_at=now,
                **updates,
            )
            self._records[transfer_id] = updated
            self._persist_locked()
            return replace(updated)

    def request_cancel(self, transfer_id: str, reason: str | None) -> TransferRecord:
        with self._lock:
            record = self._require_locked(transfer_id)
            if record.status in TERMINAL_TRANSFER_STATUSES:
                return replace(record)
            if record.status not in {"pending", "running", "cancel_requested"}:
                raise ValueError(f"cannot cancel transfer from status {record.status}")
            updated = replace(
                record,
                status="cancel_requested",
                cancel_requested=True,
                error_message=reason or record.error_message,
                updated_at=time.time(),
            )
            self._records[transfer_id] = updated
            self._persist_locked()
            return replace(updated)

    def is_cancel_requested(self, transfer_id: str) -> bool:
        with self._lock:
            record = self._records.get(transfer_id)
            return bool(record and record.cancel_requested)

    def _require_locked(self, transfer_id: str) -> TransferRecord:
        record = self._records.get(transfer_id)
        if record is None:
            raise KeyError(f"Transfer '{transfer_id}' not found")
        return record

    def _persist_progress_if_needed_locked(self, record: TransferRecord) -> None:
        last_at = self._last_persist_at.get(record.transfer_id, 0.0)
        last_bytes = self._last_persist_bytes.get(record.transfer_id, 0)
        if (
            record.updated_at - last_at >= PERSIST_INTERVAL_SECONDS
            or record.bytes_transferred - last_bytes >= PERSIST_INTERVAL_BYTES
        ):
            self._persist_locked()

    def _persist_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        records = sorted(self._records.values(), key=lambda record: record.created_at)
        raw = [transfer_to_dict(record, include_local_path=True) for record in records]
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self.path)
        now = time.time()
        for record in records:
            self._last_persist_at[record.transfer_id] = now
            self._last_persist_bytes[record.transfer_id] = record.bytes_transferred

    def _read_all(self) -> dict[str, TransferRecord]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, list):
            return {}
        records: dict[str, TransferRecord] = {}
        for item in data:
            if isinstance(item, dict):
                record = transfer_from_dict(item)
                records[record.transfer_id] = record
        return records

    def _mark_stale_active_records(self) -> bool:
        return self._mark_stale_active_records_locked(time.time(), restarting=True)

    def _mark_stale_active_records_locked(
        self,
        now: float,
        *,
        restarting: bool = False,
    ) -> bool:
        changed = False
        for transfer_id, record in list(self._records.items()):
            if record.status not in ACTIVE_TRANSFER_STATUSES:
                continue
            if not restarting and not _is_stale_active(record, now):
                continue
            started = record.started_at or record.created_at
            status: TransferStatus = "failed"
            error_type = "service_restarted"
            error_message = (
                "transfer was active when service started; "
                "restart recovery is not supported"
            )
            if not restarting:
                status = (
                    "cancelled"
                    if record.status == "cancel_requested"
                    else "timed_out"
                )
                error_type = "stale_active_transfer"
                error_message = (
                    f"transfer was {record.status} without progress for too long; "
                    "marked terminal to release transfer slot"
                )
            self._records[transfer_id] = replace(
                record,
                status=status,
                finished_at=now,
                elapsed_seconds=round(now - started, 3),
                error_type=error_type,
                error_message=error_message,
                updated_at=now,
            )
            changed = True
        return changed


def _is_stale_active(record: TransferRecord, now: float) -> bool:
    idle_seconds = now - record.updated_at
    if record.status == "cancel_requested":
        return idle_seconds >= CANCEL_REQUEST_GRACE_SECONDS
    if record.status == "pending":
        return idle_seconds >= PENDING_STALE_SECONDS
    if record.status == "running":
        return idle_seconds >= RUNNING_STALE_SECONDS
    if record.status in {"verifying", "renaming"}:
        return idle_seconds >= FINALIZING_STALE_SECONDS
    return False
