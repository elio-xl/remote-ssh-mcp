from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal


ConnectionPurpose = Literal["exec", "sftp", "long_running", "interactive"]


class SSHConnectionError(RuntimeError):
    """Base error for SSH connection failures."""


class PoolBusyError(RuntimeError):
    """No available connection and pool is at capacity."""


class SSHAcquireTimeoutError(RuntimeError):
    """Timed out waiting for an available connection."""


class SSHCommandTimeoutError(RuntimeError):
    """Command execution exceeded timeout."""


class SSHConnectionBrokenError(RuntimeError):
    """Connection was broken during use."""


@dataclass(frozen=True)
class ConnectionTarget:
    alias: str
    hostname: str
    port: int
    username: str
    auth_type: str
    identity_file: str | None = None
    password: str | None = None
    private_key_passphrase: str | None = None
    jump_host: ConnectionTarget | None = None

    def target_key(self) -> str:
        """Generate a stable key for pooling connections to this target."""
        auth_id = ":".join(
            filter(
                None,
                [
                    self.auth_type,
                    self.identity_file or "",
                    _sha256_first8(self.password) if self.password else "",
                    (
                        _sha256_first8(self.private_key_passphrase)
                        if self.private_key_passphrase
                        else ""
                    ),
                ],
            )
        )
        jump = _sha256_first8(self.jump_host.target_key()) if self.jump_host else ""
        raw = f"{self.alias}|{self.hostname}|{self.port}|{self.username}|{auth_id}|{jump}"
        return _sha256_first8(raw)


@dataclass
class SSHPoolConfig:
    core_connections_per_target: int = 1
    max_connections_per_target: int = 3
    max_channels_per_connection: int = 4
    idle_timeout_seconds: int = 600
    keepalive_seconds: int = 30
    acquire_timeout_seconds: int = 10
    connect_timeout_seconds: int = 8
    command_timeout_seconds: int = 60
    cleanup_interval_seconds: int = 60
    warmup_on_start: bool = False

    def __post_init__(self) -> None:
        _require_non_negative_int(
            "core_connections_per_target", self.core_connections_per_target
        )
        _require_positive_int("max_connections_per_target", self.max_connections_per_target)
        _require_positive_int("max_channels_per_connection", self.max_channels_per_connection)
        _require_positive_int("idle_timeout_seconds", self.idle_timeout_seconds)
        _require_positive_int("keepalive_seconds", self.keepalive_seconds)
        _require_positive_int("acquire_timeout_seconds", self.acquire_timeout_seconds)
        _require_positive_int("connect_timeout_seconds", self.connect_timeout_seconds)
        _require_positive_int("command_timeout_seconds", self.command_timeout_seconds)
        _require_positive_int("cleanup_interval_seconds", self.cleanup_interval_seconds)
        if not isinstance(self.warmup_on_start, bool):
            raise ValueError("warmup_on_start must be a boolean")
        if self.core_connections_per_target > self.max_connections_per_target:
            raise ValueError(
                "core_connections_per_target must be <= max_connections_per_target"
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SSHPoolConfig:
        if not data:
            return cls()
        valid_keys = {
            f.name
            for f in SSHPoolConfig.__dataclass_fields__.values()  # type: ignore[attr-defined]
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


@dataclass
class PooledSSHConnection:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    target_key: str = ""
    target: ConnectionTarget | None = None
    client: Any = None  # paramiko.SSHClient — avoid import at module level
    created_at: float = 0.0
    last_used_at: float = 0.0
    in_flight: int = 0
    is_core: bool = False
    is_dedicated: bool = False
    purpose: ConnectionPurpose | None = None
    aux_clients: list[Any] = field(default_factory=list)


def _sha256_first8(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:8]


def _require_positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _require_non_negative_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
