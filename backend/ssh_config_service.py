from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .paths import config_path
from .models import SSHConfigEntry, SSHConfigPayload


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = config_path()


@dataclass
class HostBlock:
    host: str
    lines: list[str]
    start: int
    end: int


def _ensure_file(path: Path = DEFAULT_CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)


def _read_lines(path: Path = DEFAULT_CONFIG_PATH) -> list[str]:
    _ensure_file(path)
    return path.read_text(encoding="utf-8").splitlines()


def _write_lines(lines: list[str], path: Path = DEFAULT_CONFIG_PATH) -> None:
    _ensure_file(path)
    if path.exists():
        shutil.copyfile(path, path.with_suffix(path.suffix + ".bak"))
    content = "\n".join(lines).rstrip()
    path.write_text(f"{content}\n" if content else "", encoding="utf-8")


def _parse_blocks(lines: list[str]) -> list[HostBlock]:
    blocks: list[HostBlock] = []
    current_start: int | None = None
    current_host = ""

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.lower().startswith("host ") and stripped.split(maxsplit=1)[0].lower() == "host":
            if current_start is not None:
                blocks.append(HostBlock(current_host, lines[current_start:idx], current_start, idx))
            current_start = idx
            current_host = stripped.split(maxsplit=1)[1].strip()

    if current_start is not None:
        blocks.append(HostBlock(current_host, lines[current_start:], current_start, len(lines)))
    return blocks


def _directives(block: HostBlock) -> dict[str, str]:
    values: dict[str, str] = {}
    comment_lines: list[str] = []
    for line in block.lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            comment = stripped[1:].strip()
            if comment.lower().startswith("remarks:"):
                values["remarks"] = comment.split(":", 1)[1].strip()
            elif comment.lower().startswith("workdir:"):
                values["workdir"] = comment.split(":", 1)[1].strip()
            else:
                comment_lines.append(comment)
            continue
        parts = stripped.split(maxsplit=1)
        if len(parts) == 2:
            values[parts[0].lower()] = parts[1].strip()
    if "remarks" not in values and comment_lines:
        values["remarks"] = " ".join(comment_lines)
    return values


def _block_to_entry(block: HostBlock) -> SSHConfigEntry:
    values = _directives(block)
    identity_file = values.get("identityfile", "")
    return SSHConfigEntry(
        host=block.host,
        hostname=values.get("hostname", ""),
        user=values.get("user", "root"),
        port=int(values.get("port", "22") or 22),
        type="key" if identity_file else "password",
        IdentityFile=identity_file,
        password="",
        workdir=values.get("workdir", ""),
        remarks=values.get("remarks", ""),
    )


def _payload_to_block(payload: SSHConfigPayload) -> list[str]:
    lines = [
        f"Host {payload.host}",
        f"    HostName {payload.hostname}",
        f"    User {payload.user}",
        f"    Port {payload.port}",
    ]
    if payload.type == "key" and payload.IdentityFile:
        lines.append(f"    IdentityFile {payload.IdentityFile}")
    if payload.workdir:
        lines.append(f"    # Workdir: {payload.workdir}")
    if payload.remarks:
        lines.append(f"    # Remarks: {payload.remarks}")
    return lines


def list_entries() -> list[SSHConfigEntry]:
    lines = _read_lines()
    return [_block_to_entry(block) for block in _parse_blocks(lines)]


def get_entry(host: str) -> SSHConfigEntry | None:
    for entry in list_entries():
        if entry.host == host:
            return entry
    return None


def create_entry(payload: SSHConfigPayload) -> SSHConfigEntry:
    if get_entry(payload.host):
        raise ValueError(f"Host '{payload.host}' 已存在")
    lines = _read_lines()
    if lines and lines[-1].strip():
        lines.append("")
    lines.extend(_payload_to_block(payload))
    _write_lines(lines)
    return get_entry(payload.host) or SSHConfigEntry(**{**payload.model_dump(), "password": ""})


def update_entry(host: str, payload: SSHConfigPayload) -> SSHConfigEntry:
    lines = _read_lines()
    blocks = _parse_blocks(lines)
    target = next((block for block in blocks if block.host == host), None)
    if target is None:
        raise KeyError(f"Host '{host}' 未找到")
    if payload.host != host and get_entry(payload.host):
        raise ValueError(f"Host '{payload.host}' 已存在")

    updated = lines[: target.start] + _payload_to_block(payload) + lines[target.end :]
    _write_lines(updated)
    return get_entry(payload.host) or SSHConfigEntry(**{**payload.model_dump(), "password": ""})


def delete_entry(host: str) -> None:
    lines = _read_lines()
    blocks = _parse_blocks(lines)
    target = next((block for block in blocks if block.host == host), None)
    if target is None:
        raise KeyError(f"Host '{host}' 未找到")
    updated = lines[: target.start] + lines[target.end :]
    while updated and not updated[0].strip():
        updated.pop(0)
    _write_lines(updated)


def rename_entry(host: str, new_host: str) -> SSHConfigEntry:
    entry = get_entry(host)
    if entry is None:
        raise KeyError(f"Host '{host}' 未找到")
    payload = SSHConfigPayload(**{**entry.model_dump(), "host": new_host, "password": "placeholder-password" if entry.type == "password" else ""})
    return update_entry(host, payload)
