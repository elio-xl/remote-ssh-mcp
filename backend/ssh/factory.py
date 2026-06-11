from __future__ import annotations

import socket
from pathlib import Path

import paramiko

from .models import ConnectionTarget, SSHConnectionError


class SSHConnectionFactory:
    """Creates paramiko SSH clients with optional jump host support."""

    def __init__(
        self,
        connect_timeout_seconds: int = 8,
        keepalive_seconds: int = 30,
    ) -> None:
        self._connect_timeout = connect_timeout_seconds
        self._keepalive = keepalive_seconds

    def create(self, target: ConnectionTarget) -> paramiko.SSHClient:
        client, aux_clients = self.create_bundle(target)
        if aux_clients:
            setattr(client, "_adremote_aux_clients", aux_clients)
        return client

    def create_bundle(
        self, target: ConnectionTarget
    ) -> tuple[paramiko.SSHClient, list[paramiko.SSHClient]]:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        aux_clients: list[paramiko.SSHClient] = []

        if target.jump_host is not None:
            aux_clients = self._connect_via_jump(client, target)
        else:
            self._connect_direct(client, target)

        transport = client.get_transport()
        if transport is not None:
            transport.set_keepalive(self._keepalive)
        return client, aux_clients

    def _connect_direct(self, client: paramiko.SSHClient, target: ConnectionTarget) -> None:
        kwargs = self._auth_kwargs(target)
        try:
            client.connect(**kwargs)
        except (paramiko.SSHException, socket.error, OSError) as exc:
            client.close()
            raise SSHConnectionError(
                f"SSH connect to {target.hostname}:{target.port} failed: {exc}"
            ) from exc

    def _connect_via_jump(
        self, client: paramiko.SSHClient, target: ConnectionTarget
    ) -> list[paramiko.SSHClient]:
        assert target.jump_host is not None
        jump_client = paramiko.SSHClient()
        jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        jump_kwargs = self._auth_kwargs(target.jump_host)
        try:
            jump_client.connect(**jump_kwargs)
        except (paramiko.SSHException, socket.error, OSError) as exc:
            jump_client.close()
            raise SSHConnectionError(
                "SSH connect to jump host "
                f"{target.jump_host.hostname}:{target.jump_host.port} failed: {exc}"
            ) from exc

        try:
            jump_transport = jump_client.get_transport()
            if jump_transport is None:
                raise SSHConnectionError("Jump host transport is None")
            channel = jump_transport.open_channel(
                "direct-tcpip",
                (target.hostname, target.port),
                ("127.0.0.1", 0),
            )
            kwargs = self._auth_kwargs(target)
            kwargs["sock"] = channel
            client.connect(**kwargs)
            return [jump_client]
        except (paramiko.SSHException, socket.error, OSError) as exc:
            client.close()
            jump_client.close()
            raise SSHConnectionError(
                f"SSH connect via jump to {target.hostname}:{target.port} failed: {exc}"
            ) from exc

    def _auth_kwargs(self, target: ConnectionTarget) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "hostname": target.hostname,
            "port": target.port,
            "username": target.username,
            "timeout": self._connect_timeout,
            "banner_timeout": self._connect_timeout,
            "auth_timeout": self._connect_timeout,
            "look_for_keys": False,
            "allow_agent": False,
        }
        if target.auth_type == "password":
            kwargs["password"] = target.password or ""
        else:
            kwargs["key_filename"] = _expand_path(target.identity_file or "")
            if target.private_key_passphrase:
                kwargs["passphrase"] = target.private_key_passphrase
        return kwargs


def _expand_path(value: str) -> str:
    return str(Path(value).expanduser())
