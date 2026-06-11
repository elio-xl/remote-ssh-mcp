from __future__ import annotations

import hashlib
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.ssh.models import ConnectionTarget
from backend.ssh.sftp import remote_file_exists

from .models import PlanStep


MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB


@dataclass(frozen=True)
class RemoteReplaceResult:
    backup_path: str = ""
    backup_cleanup_failed: bool = False


class RemoteReplaceError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        backup_path: str = "",
        restored: bool = False,
    ) -> None:
        super().__init__(message)
        self.backup_path = backup_path
        self.restored = restored

REMOTE_PATH_DENYLIST_EXACT: set[str] = {
    "/boot",
    "/dev",
    "/etc/group",
    "/etc/passwd",
    "/etc/shadow",
    "/etc/ssh/sshd_config",
    "/etc/sudoers",
    "/proc",
    "/root/.ssh/authorized_keys",
    "/sys",
}

REMOTE_PATH_DENYLIST_PREFIX: tuple[str, ...] = (
    "/boot/",
    "/dev/",
    "/etc/ssh/",
    "/proc/",
    "/root/.ssh/",
    "/sys/",
)


def resolve_local_path(raw: str) -> Path | None:
    if not raw.strip():
        return None
    return Path(raw).expanduser().resolve()


def validate_local_file(path: Path) -> str | None:
    if not path.exists():
        return f"local file does not exist: {path}"
    if not path.is_file():
        return f"local path is not a regular file: {path}"
    if not os.access(path, os.R_OK):
        return f"local file is not readable: {path}"
    parts = set(path.parts)
    if parts & {".ssh", ".gnupg", ".aws", ".gcloud", ".azure"}:
        return f"local path references sensitive directory: {path}"
    resolved = str(path)
    if "/etc/shadow" in resolved or "/private/etc/shadow" in resolved:
        return f"local path references sensitive file: {path}"
    return None


def validate_remote_path(remote_path: str) -> str | None:
    if not remote_path.startswith("/"):
        return "remote_path must be an absolute path"
    if ".." in remote_path.split("/"):
        return "remote_path must not contain path traversal"
    resolved = os.path.normpath(remote_path)
    if resolved in REMOTE_PATH_DENYLIST_EXACT:
        return f"remote_path is in denylist: {resolved}"
    for prefix in REMOTE_PATH_DENYLIST_PREFIX:
        if resolved.startswith(prefix):
            return f"remote_path is in denylist: {resolved}"
    if len(resolved) > 4096:
        return "remote_path exceeds maximum length"
    return None


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(256 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def temp_path(remote_path: str) -> str:
    digest = hashlib.sha256(remote_path.encode("utf-8")).hexdigest()[:12]
    return remote_path + f".part.{digest}"


def unique_temp_path(remote_path: str) -> str:
    return remote_path + f".tmp.{uuid.uuid4().hex[:12]}"


def build_backup_path(remote_path: str, suffix_template: str) -> str:
    ts = str(int(time.time()))
    suffix = suffix_template.replace("{timestamp}", ts).replace("{sha256_8}", "backup")
    return remote_path + suffix


def build_rename_new_path(remote_path: str) -> str:
    p = Path(remote_path)
    ts = str(int(time.time()))
    return str(p.parent / f"{p.stem}.{ts}{p.suffix}")


def rename_remote(conn: object, old_path: str, new_path: str) -> None:
    client = conn.client
    sftp = client.open_sftp()
    try:
        sftp.rename(old_path, new_path)
    finally:
        sftp.close()


def chmod_remote(conn: object, remote_path: str, mode: str) -> None:
    client = conn.client
    sftp = client.open_sftp()
    try:
        sftp.chmod(remote_path, int(mode, 8))
    finally:
        sftp.close()


def delete_remote(conn: object, remote_path: str) -> bool:
    try:
        client = conn.client
        sftp = client.open_sftp()
        try:
            sftp.remove(remote_path)
        finally:
            sftp.close()
        return True
    except Exception:
        return False


def restore_backup(conn: object, backup_path: str, original_path: str) -> bool:
    try:
        rename_remote(conn, backup_path, original_path)
        return True
    except Exception:
        return False


def replace_remote(
    conn: object,
    temp_remote_path: str,
    remote_path: str,
) -> RemoteReplaceResult:
    """Replace remote_path with temp_remote_path without leaving target missing.

    Prefer OpenSSH's posix_rename extension because it overwrites atomically.
    If unavailable, move the old target to a hidden backup, rename the new file,
    and restore the old target if the final rename fails.
    """
    client = conn.client
    sftp = client.open_sftp()
    try:
        posix_rename = getattr(sftp, "posix_rename", None)
        if callable(posix_rename):
            posix_rename(temp_remote_path, remote_path)
            return RemoteReplaceResult()
    finally:
        sftp.close()

    fallback_backup = unique_temp_path(remote_path) + ".old"
    rename_remote(conn, remote_path, fallback_backup)
    try:
        rename_remote(conn, temp_remote_path, remote_path)
    except Exception as exc:
        restored = restore_backup(conn, fallback_backup, remote_path)
        message = str(exc)
        if not restored:
            message = f"{message}; original file remains at {fallback_backup}"
        raise RemoteReplaceError(
            message,
            backup_path=fallback_backup,
            restored=restored,
        ) from exc
    cleanup_failed = not delete_remote(conn, fallback_backup)
    return RemoteReplaceResult(fallback_backup, cleanup_failed)


def set_transport_timeout(conn: object, timeout_seconds: float) -> None:
    try:
        client = conn.client
        transport = client.get_transport()
        if transport is not None:
            transport.settimeout(timeout_seconds)
    except Exception:
        pass


def check_timeout(deadline: float, stage: str) -> None:
    if time.time() > deadline:
        raise TimeoutError(f"sftp_put timed out during {stage}")


def preview_remote_state(
    pool: Any,
    target: ConnectionTarget,
    steps: list[PlanStep],
) -> list[dict[str, object]]:
    sftp_steps = [
        (i, step)
        for i, step in enumerate(steps)
        if step.instruction and step.instruction.kind == "sftp_put"
    ]
    if not sftp_steps:
        return []

    try:
        conn = pool.acquire(target, purpose="sftp", timeout=5)
    except Exception:
        return []

    conflicts: list[dict[str, object]] = []
    try:
        for idx, step in sftp_steps:
            remote_path = step.instruction.remote_path or ""
            if not remote_path:
                continue
            try:
                exists = remote_file_exists(conn, remote_path)
                conflicts.append(
                    {
                        "instruction_index": idx,
                        "remote_path": remote_path,
                        "exists": exists,
                        "conflict_policy": step.instruction.conflict_policy,
                    }
                )
            except Exception:
                conflicts.append(
                    {
                        "instruction_index": idx,
                        "remote_path": remote_path,
                        "exists": None,
                        "error": "check_failed",
                        "conflict_policy": step.instruction.conflict_policy,
                    }
                )
    finally:
        try:
            pool.release(conn)
        except Exception:
            pass

    return conflicts
