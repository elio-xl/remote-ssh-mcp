from __future__ import annotations

import socket
from pathlib import Path

from .models import SSHConfigPayload


def _expand_path(value: str) -> str:
    return str(Path(value).expanduser())


def _check_tcp_reachable(hostname: str, port: int, timeout: int) -> None:
    try:
        with socket.create_connection((hostname, port), timeout=timeout):
            return
    except socket.timeout as exc:
        raise RuntimeError(f"连接超时：无法在 {timeout} 秒内连接到 {hostname}:{port}") from exc
    except ConnectionRefusedError as exc:
        raise RuntimeError(f"端口被拒绝：{hostname}:{port} 未监听 SSH 服务或被安全组/防火墙拒绝") from exc
    except OSError as exc:
        reason = str(exc).strip() or exc.__class__.__name__
        raise RuntimeError(f"TCP 连接失败：{hostname}:{port}，{reason}") from exc


def test_connection(payload: SSHConfigPayload, timeout: int = 8) -> str:
    _check_tcp_reachable(payload.hostname, payload.port, timeout)

    try:
        import paramiko
    except Exception as exc:
        raise RuntimeError("当前 Python 环境未安装可用的 paramiko，无法测试连接") from exc
    if not hasattr(paramiko, "SSHClient"):
        raise RuntimeError("当前 Python 环境未安装可用的 paramiko，无法测试连接")

    client = None
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: dict[str, object] = {
            "hostname": payload.hostname,
            "port": payload.port,
            "username": payload.user,
            "timeout": timeout,
            "banner_timeout": timeout,
            "auth_timeout": timeout,
            "look_for_keys": False,
            "allow_agent": False,
        }
        if payload.type == "password":
            kwargs["password"] = payload.password
        else:
            kwargs["key_filename"] = _expand_path(payload.IdentityFile)
        client.connect(**kwargs)
        return "连接测试成功"
    except getattr(paramiko, "AuthenticationException", Exception) as exc:
        raise RuntimeError("认证失败") from exc
    except TimeoutError as exc:
        raise RuntimeError("连接超时") from exc
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        raise RuntimeError(message) from exc
    finally:
        if client is not None:
            client.close()
