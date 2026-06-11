from __future__ import annotations

import errno
import hashlib
import socket
import shlex
import time
from pathlib import Path
from typing import Callable, Literal

from .models import PooledSSHConnection, SSHConnectionBrokenError

UploadMethod = Literal["sftp", "scp"]
Checkpoint = Callable[[], None]
SFTP_CHUNK_SIZE = 1024 * 1024
SCP_CHUNK_SIZE = 1024 * 1024
SCP_CHANNEL_POLL_SECONDS = 0.25
SCP_CHANNEL_SEND_BYTES = 32 * 1024


def upload_file(
    conn: PooledSSHConnection,
    local_path: str,
    remote_path: str,
    callback: Callable[[int, int], None] | None = None,
    confirm: bool = False,
    resume: bool = True,
    checkpoint: Checkpoint | None = None,
) -> None:
    """Upload a local file to the remote host via chunked SFTP.

    The caller must acquire/release the pooled connection::

        conn = pool.acquire(target, purpose="sftp")
        try:
            upload_file(conn, "/local/file", "/remote/file")
        finally:
            pool.release(conn)
    """
    client = conn.client
    if client is None:
        raise SSHConnectionBrokenError("Connection client is None")

    sftp = client.open_sftp()
    try:
        _upload_file_sftp_chunked(
            sftp,
            local_path,
            remote_path,
            callback=callback,
            confirm=confirm,
            resume=resume,
            checkpoint=checkpoint,
        )
    finally:
        sftp.close()


def upload_file_with_method(
    conn: PooledSSHConnection,
    local_path: str,
    remote_path: str,
    *,
    method: UploadMethod = "sftp",
    callback: Callable[[int, int], None] | None = None,
    confirm: bool = False,
    resume: bool = True,
    checkpoint: Checkpoint | None = None,
) -> None:
    if method == "sftp":
        upload_file(
            conn,
            local_path,
            remote_path,
            callback=callback,
            confirm=confirm,
            resume=resume,
            checkpoint=checkpoint,
        )
        return
    if method == "scp":
        upload_file_scp(
            conn,
            local_path,
            remote_path,
            callback=callback,
            checkpoint=checkpoint,
        )
        return
    raise ValueError(f"unsupported upload method: {method}")


def upload_file_scp(
    conn: PooledSSHConnection,
    local_path: str,
    remote_path: str,
    callback: Callable[[int, int], None] | None = None,
    checkpoint: Checkpoint | None = None,
) -> None:
    """Upload a local file using the remote scp sink protocol."""
    client = conn.client
    if client is None:
        raise SSHConnectionBrokenError("Connection client is None")

    local_file = Path(local_path)
    file_size = local_file.stat().st_size
    transport = client.get_transport()
    if transport is None:
        raise SSHConnectionBrokenError("Connection transport is None")

    channel = transport.open_session()
    try:
        settimeout = getattr(channel, "settimeout", None)
        if callable(settimeout):
            settimeout(0.0)
        _run_checkpoint(checkpoint)
        channel.exec_command(f"scp -t {shlex.quote(remote_path)}")
        _run_checkpoint(checkpoint)
        _read_scp_ack(channel, checkpoint)
        filename = local_file.name or "upload"
        header = f"C0644 {file_size} {filename}\n".encode("utf-8")
        _run_checkpoint(checkpoint)
        _send_all_nonblocking(channel, header, checkpoint)
        _run_checkpoint(checkpoint)
        _read_scp_ack(channel, checkpoint)

        transferred = 0
        with local_file.open("rb") as handle:
            while True:
                _run_checkpoint(checkpoint)
                chunk = handle.read(SCP_CHUNK_SIZE)
                if not chunk:
                    break
                _send_all_nonblocking(channel, chunk, checkpoint)
                transferred += len(chunk)
                if callback is not None:
                    callback(transferred, file_size)

        _run_checkpoint(checkpoint)
        _send_all_nonblocking(channel, b"\x00", checkpoint)
        _run_checkpoint(checkpoint)
        _read_scp_ack(channel, checkpoint)
    finally:
        channel.close()


def _upload_file_sftp_chunked(
    sftp: object,
    local_path: str,
    remote_path: str,
    *,
    callback: Callable[[int, int], None] | None,
    confirm: bool,
    resume: bool,
    checkpoint: Checkpoint | None,
) -> None:
    local_file = Path(local_path)
    file_size = local_file.stat().st_size
    _run_checkpoint(checkpoint)
    offset = (
        _remote_resume_offset(
            sftp,
            local_file,
            remote_path,
            file_size,
            checkpoint,
        )
        if resume
        else 0
    )
    if offset >= file_size:
        if callback is not None:
            callback(file_size, file_size)
        if confirm:
            _confirm_remote_size(sftp, remote_path, file_size)
        return

    mode = "ab" if offset > 0 else "wb"
    with local_file.open("rb") as source:
        source.seek(offset)
        with sftp.open(remote_path, mode) as target:
            transferred = offset
            while True:
                _run_checkpoint(checkpoint)
                chunk = source.read(SFTP_CHUNK_SIZE)
                if not chunk:
                    break
                target.write(chunk)
                transferred += len(chunk)
                if callback is not None:
                    callback(transferred, file_size)
            flush = getattr(target, "flush", None)
            if callable(flush):
                flush()

    if confirm:
        _confirm_remote_size(sftp, remote_path, file_size)


def _remote_resume_offset(
    sftp: object,
    local_file: Path,
    remote_path: str,
    file_size: int,
    checkpoint: Checkpoint | None,
) -> int:
    try:
        remote_size = int(sftp.stat(remote_path).st_size)
    except OSError as exc:
        if (
            getattr(exc, "errno", None) == errno.ENOENT
            or str(exc).startswith("[Errno 2]")
        ):
            return 0
        raise
    if remote_size < 0 or remote_size > file_size:
        return 0
    if remote_size == 0:
        return 0
    if not _prefix_hashes_match(
        sftp,
        local_file,
        remote_path,
        remote_size,
        checkpoint,
    ):
        return 0
    return remote_size


def _prefix_hashes_match(
    sftp: object,
    local_file: Path,
    remote_path: str,
    byte_count: int,
    checkpoint: Checkpoint | None,
) -> bool:
    local_hasher = hashlib.sha256()
    remote_hasher = hashlib.sha256()
    remaining = byte_count
    with local_file.open("rb") as local_handle:
        with sftp.open(remote_path, "rb") as remote_handle:
            while remaining > 0:
                _run_checkpoint(checkpoint)
                read_size = min(SFTP_CHUNK_SIZE, remaining)
                local_chunk = local_handle.read(read_size)
                remote_chunk = remote_handle.read(read_size)
                if not local_chunk or not remote_chunk:
                    return False
                if len(local_chunk) != len(remote_chunk):
                    return False
                local_hasher.update(local_chunk)
                remote_hasher.update(remote_chunk)
                remaining -= len(local_chunk)
    return local_hasher.digest() == remote_hasher.digest()


def _run_checkpoint(checkpoint: Checkpoint | None) -> None:
    if checkpoint is not None:
        checkpoint()


def _confirm_remote_size(sftp: object, remote_path: str, expected_size: int) -> None:
    actual_size = int(sftp.stat(remote_path).st_size)
    if actual_size != expected_size:
        raise OSError(
            f"SFTP upload confirmation failed: expected {expected_size} bytes, "
            f"got {actual_size}"
        )


def download_file(
    conn: PooledSSHConnection,
    remote_path: str,
    local_path: str,
    callback: Callable[[int, int], None] | None = None,
) -> None:
    """Download a remote file to the local host via SFTP."""
    client = conn.client
    if client is None:
        raise SSHConnectionBrokenError("Connection client is None")

    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    sftp = client.open_sftp()
    try:
        sftp.get(remote_path, local_path, callback=callback)
    finally:
        sftp.close()


def _send_all_nonblocking(
    channel: object,
    data: bytes,
    checkpoint: Checkpoint | None,
) -> None:
    offset = 0
    total = len(data)
    while offset < total:
        _run_checkpoint(checkpoint)
        send_ready = getattr(channel, "send_ready", None)
        if callable(send_ready) and not send_ready():
            _wait_for_channel(checkpoint)
            continue
        try:
            chunk = data[offset : offset + SCP_CHANNEL_SEND_BYTES]
            send = getattr(channel, "send", None)
            if callable(send):
                sent = send(chunk)
            else:
                channel.sendall(chunk)
                sent = len(chunk)
        except socket.timeout:
            _wait_for_channel(checkpoint)
            continue
        if sent is None:
            sent = 0
        if sent <= 0:
            _wait_for_channel(checkpoint)
            continue
        offset += sent


def _read_scp_ack(channel: object, checkpoint: Checkpoint | None) -> None:
    response = _recv_scp_byte(channel, checkpoint)
    if response == b"\x00":
        return
    if response in {b"\x01", b"\x02"}:
        message = _read_scp_error(channel, checkpoint)
        raise OSError(f"scp upload failed: {message}")
    if response == b"":
        raise OSError("scp upload failed: connection closed")
    raise OSError(f"scp upload failed: unexpected response {response!r}")


def _read_scp_error(channel: object, checkpoint: Checkpoint | None) -> str:
    parts: list[bytes] = []
    while True:
        chunk = _recv_scp_byte(channel, checkpoint)
        if chunk in {b"", b"\n"}:
            break
        parts.append(chunk)
    if not parts:
        return "remote scp returned an error"
    return b"".join(parts).decode("utf-8", errors="replace")


def _recv_scp_byte(channel: object, checkpoint: Checkpoint | None) -> bytes:
    while True:
        _run_checkpoint(checkpoint)
        recv_ready = getattr(channel, "recv_ready", None)
        if callable(recv_ready) and not recv_ready():
            if _channel_closed(channel):
                return b""
            _wait_for_channel(checkpoint)
            continue
        try:
            return channel.recv(1)
        except socket.timeout:
            _wait_for_channel(checkpoint)


def _wait_for_channel(checkpoint: Checkpoint | None) -> None:
    _run_checkpoint(checkpoint)
    time.sleep(SCP_CHANNEL_POLL_SECONDS)


def _channel_closed(channel: object) -> bool:
    closed = getattr(channel, "closed", False)
    if isinstance(closed, bool) and closed:
        return True
    exit_ready = getattr(channel, "exit_status_ready", None)
    return bool(callable(exit_ready) and exit_ready())


def compute_remote_hash(
    conn: PooledSSHConnection,
    remote_path: str,
    algorithm: str = "sha256",
    chunk_size: int = 1024 * 1024,
) -> str:
    """Compute a hash of a remote file.

    Prefer a remote checksum command so large-file verification does not pull
    the uploaded file back over SFTP. Fall back to SFTP streaming when needed.
    """
    client = conn.client
    if client is None:
        raise SSHConnectionBrokenError("Connection client is None")

    if algorithm == "sha256":
        remote_hash = _compute_remote_sha256_with_command(client, remote_path)
        if remote_hash:
            return remote_hash

    hasher = hashlib.new(algorithm)
    sftp = client.open_sftp()
    try:
        with sftp.open(remote_path, "rb") as f:
            prefetch = getattr(f, "prefetch", None)
            if callable(prefetch):
                prefetch()
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                hasher.update(chunk)
    finally:
        sftp.close()

    return hasher.hexdigest()


def _compute_remote_sha256_with_command(client: object, remote_path: str) -> str | None:
    quoted = shlex.quote(remote_path)
    commands = (
        f"sha256sum -b -- {quoted}",
        f"shasum -a 256 -- {quoted}",
    )
    for command in commands:
        try:
            _stdin, stdout, stderr = client.exec_command(command, timeout=30)
            exit_status = stdout.channel.recv_exit_status()
            output = stdout.read().decode("utf-8", errors="replace").strip()
            _ = stderr.read()
        except Exception:
            continue
        if exit_status != 0 or not output:
            continue
        digest = output.split(maxsplit=1)[0].strip()
        if len(digest) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in digest):
            return digest.lower()
    return None


def remote_file_exists(conn: PooledSSHConnection, remote_path: str) -> bool:
    client = conn.client
    if client is None:
        raise SSHConnectionBrokenError("Connection client is None")

    sftp = client.open_sftp()
    try:
        sftp.stat(remote_path)
        return True
    except OSError as exc:
        if (
            getattr(exc, "errno", None) == errno.ENOENT
            or str(exc).startswith("[Errno 2]")
        ):
            return False
        raise
    finally:
        sftp.close()
