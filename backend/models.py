from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


AuthType = Literal["password", "key"]


@dataclass
class SSHConfigEntry:
    host: str
    hostname: str = ""
    user: str = "root"
    port: int = 22
    type: AuthType = "password"
    IdentityFile: str = ""
    password: str = ""
    workdir: str = ""
    remarks: str = ""

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


SSHConfigPayload = SSHConfigEntry


def payload_from_dict(data: dict[str, Any]) -> SSHConfigPayload:
    try:
        port = int(data.get("port", 22))
    except (TypeError, ValueError) as exc:
        raise ValueError("Port 必须是 1-65535 之间的整数") from exc

    payload = SSHConfigPayload(
        host=str(data.get("host", "")).strip(),
        hostname=str(data.get("hostname", "")).strip(),
        user=str(data.get("user", "root")).strip(),
        port=port,
        type=data.get("type", ""),
        IdentityFile=str(data.get("IdentityFile", "")).strip(),
        password=str(data.get("password", "")).strip(),
        workdir=str(data.get("workdir", "")).strip(),
        remarks=str(data.get("remarks", "")).strip(),
    )
    validate_payload(payload)
    return payload


def validate_payload(payload: SSHConfigPayload) -> None:
    if not payload.host:
        raise ValueError("Host 为必填项")
    if not payload.hostname:
        raise ValueError("HostName 为必填项")
    if not payload.user:
        raise ValueError("User 为必填项")
    if not isinstance(payload.port, int) or payload.port < 1 or payload.port > 65535:
        raise ValueError("Port 必须是 1-65535 之间的整数")
    if payload.type not in ("password", "key"):
        raise ValueError("请选择连接类型")
    if payload.type == "password" and not payload.password:
        raise ValueError("密码连接必须填写 Password")
    if payload.type == "key" and not payload.IdentityFile:
        raise ValueError("密钥连接必须填写 IdentityFile")

