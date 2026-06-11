from __future__ import annotations

import time
from dataclasses import dataclass

from .models import (
    PooledSSHConnection,
    SSHCommandTimeoutError,
    SSHConnectionBrokenError,
)


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    exit_code: int
    elapsed_seconds: float


def exec_command(
    conn: PooledSSHConnection,
    command: str,
    timeout: int = 60,
    workdir: str = "",
) -> CommandResult:
    """Execute a command on a pooled connection using an independent channel.

    The caller must acquire/release the pooled connection around this call::

        conn = pool.acquire(target, purpose="exec")
        try:
            result = exec_command(conn, "ls -la")
        finally:
            pool.release(conn)
    """
    if workdir:
        command = f"cd {_quote(workdir)} && {{ {command}; }}"

    client = conn.client
    if client is None:
        raise SSHConnectionBrokenError("Connection client is None")

    started = time.monotonic()
    try:
        transport = client.get_transport()
        if transport is None or not transport.is_active():
            raise SSHConnectionBrokenError("Connection transport is not active")
        channel = transport.open_session(timeout=timeout)
        channel.settimeout(1.0)
        channel.exec_command(command)
    except Exception as exc:
        raise SSHConnectionBrokenError(f"Failed to open channel: {exc}") from exc

    out_chunks: list[bytes] = []
    err_chunks: list[bytes] = []
    deadline = started + timeout
    try:
        while True:
            while channel.recv_ready():
                out_chunks.append(channel.recv(32768))
            while channel.recv_stderr_ready():
                err_chunks.append(channel.recv_stderr(32768))

            if channel.exit_status_ready():
                while channel.recv_ready():
                    out_chunks.append(channel.recv(32768))
                while channel.recv_stderr_ready():
                    err_chunks.append(channel.recv_stderr(32768))
                exit_code = channel.recv_exit_status()
                break

            if time.monotonic() > deadline:
                raise SSHCommandTimeoutError(f"Command timed out after {timeout}s")

            time.sleep(0.02)
    except Exception as exc:
        if isinstance(exc, SSHCommandTimeoutError):
            raise
        raise SSHConnectionBrokenError(f"Command channel error: {exc}") from exc
    finally:
        try:
            channel.close()
        except Exception:
            pass

    out = b"".join(out_chunks).decode("utf-8", errors="replace")
    err = b"".join(err_chunks).decode("utf-8", errors="replace")
    elapsed = time.monotonic() - started
    return CommandResult(
        stdout=out,
        stderr=err,
        exit_code=exit_code,
        elapsed_seconds=round(elapsed, 3),
    )


def _quote(s: str) -> str:
    """Minimal shell quoting for a directory path."""
    if "'" not in s:
        return f"'{s}'"
    escaped = s.replace("'", "'\\''")
    return f"'{escaped}'"
