from __future__ import annotations

import re
import shlex
from dataclasses import asdict
from ipaddress import ip_address

from .models import Instruction, InstructionPreview, PolicyResult, RiskLevel


SECRET_PATTERNS = [
    re.compile(r"(?i)(password|passwd|passphrase|token|secret|api[_-]?key)(\s*[=:]\s*)([^\s'\"]+)"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
]
IPV4_CANDIDATE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
SENSITIVE_PATH = re.compile(
    r"(?i)(/etc/shadow|/etc/sudoers|\.ssh/(id_[a-z0-9_]+|authorized_keys|known_hosts)|(?:^|[\s/])\.env(?:$|[\s'])|credential|secret|token|private[_-]?key)"
)
DANGEROUS_OPERATORS = re.compile(r"(;|&&|\|\||\||>|<|`|\$\(|\n)")
LOW_RISK_COMMANDS = {"pwd", "whoami", "id", "uname", "uptime", "date"}
LOW_RISK_PREFIXES = {"ls", "df", "free", "ps", "top", "du", "cat", "head", "tail", "grep", "find"}
HIGH_RISK_BINARIES = {
    "rm",
    "rmdir",
    "mv",
    "cp",
    "chmod",
    "chown",
    "dd",
    "mkfs",
    "mount",
    "umount",
    "reboot",
    "shutdown",
    "iptables",
    "ufw",
    "firewall-cmd",
    "systemctl",
    "service",
    "docker",
    "kubectl",
    "tee",
    "sed",
}

READONLY_SUBCOMMANDS: dict[str, set[str]] = {
    "docker": {
        "ps", "logs", "images", "image", "inspect", "info", "version",
        "stats", "top", "diff", "events", "history", "context",
        "container", "system", "network", "volume", "compose",
        "search", "manifest",
    },
    "kubectl": {
        "get", "describe", "logs", "explain", "top",
        "config", "api-resources", "api-versions", "cluster-info",
        "version", "auth", "certificate",
    },
    "systemctl": {
        "status", "is-active", "is-enabled", "list-units",
        "list-unit-files", "list-timers", "list-dependencies",
        "list-jobs", "show", "cat", "help",
    },
    "service": {"status", "--status-all"},
}

DOCKER_READONLY_SUB2: dict[str, set[str]] = {
    "container": {"ls", "inspect", "logs", "top", "stats", "diff"},
    "image": {"ls", "inspect", "history"},
    "system": {"info", "df", "events"},
    "network": {"ls", "inspect"},
    "volume": {"ls", "inspect"},
    "compose": {"ps", "logs", "config", "images", "version"},
}

KUBECTL_READONLY_SUB2: dict[str, set[str]] = {
    "config": {"view", "current-context", "get-contexts"},
    "auth": {"can-i"},
}


def redact_text(text: str | None, patterns: list[str] | None = None) -> str:
    if not text:
        return ""
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(_redact_match, redacted)
    redacted = IPV4_CANDIDATE.sub(_redact_public_ipv4, redacted)
    for raw_pattern in patterns or []:
        try:
            redacted = re.sub(raw_pattern, "[REDACTED]", redacted)
        except re.error:
            continue
    return redacted


def classify_instruction(instruction: Instruction) -> PolicyResult:
    if instruction.kind == "shell":
        return _classify_shell(instruction)
    if instruction.kind == "interactive":
        return PolicyResult("require_approval", "high", "interactive sessions can change remote state", "interactive")
    if instruction.kind == "read_file":
        if not instruction.remote_path:
            return PolicyResult("block", "medium", "read_file requires remote_path", "invalid_read_file")
        if SENSITIVE_PATH.search(instruction.remote_path):
            return PolicyResult("block", "high", "sensitive file path is blocked", "sensitive_path")
        return PolicyResult("allow", "low", "ordinary remote file read", "read_file")
    if instruction.kind == "write_file":
        return PolicyResult("require_approval", "medium", "controlled file write with backup", "write_file")
    if instruction.kind == "sftp_put":
        return PolicyResult("require_approval", "high", "file upload changes remote state", "sftp_put")
    if instruction.kind == "sftp_get":
        if instruction.remote_path and SENSITIVE_PATH.search(instruction.remote_path):
            return PolicyResult("require_approval", "medium", "download may expose sensitive remote file", "sensitive_path")
        return PolicyResult("allow", "low", "ordinary remote file download", "sftp_get")
    return PolicyResult("block", "high", "unsupported instruction kind", "unsupported")


def preview_instruction(instruction: Instruction) -> InstructionPreview:
    result = classify_instruction(instruction)
    display = _instruction_display(instruction)
    redacted = redact_text(display, instruction.redaction_patterns)
    return InstructionPreview(
        kind=instruction.kind,
        display=redacted,
        risk_level=result.risk_level,
        redacted=redacted != display,
    )


def policy_to_dict(result: PolicyResult) -> dict[str, str | None]:
    return asdict(result)


def _classify_shell(instruction: Instruction) -> PolicyResult:
    command = (instruction.command or "").strip()
    if not command:
        return PolicyResult("block", "medium", "shell command is required", "invalid_shell")
    if instruction.timeout_seconds < 1:
        return PolicyResult("block", "medium", "timeout must be positive", "invalid_timeout")
    if SENSITIVE_PATH.search(command):
        return PolicyResult("block", "high", "command references a sensitive path", "sensitive_path")
    if DANGEROUS_OPERATORS.search(command):
        return PolicyResult("require_approval", "high", "complex shell operators require approval", "shell_operator")

    try:
        parts = shlex.split(command)
    except ValueError:
        return PolicyResult("require_approval", "medium", "command cannot be parsed safely", "parse_error")
    if not parts:
        return PolicyResult("block", "medium", "shell command is required", "invalid_shell")

    binary = _strip_sudo(parts)[0]
    if binary in LOW_RISK_COMMANDS:
        return PolicyResult("allow", "low", "allowlisted read-only command", "allowlist")
    if binary in LOW_RISK_PREFIXES:
        return PolicyResult("allow", "low", "allowlisted read-only command family", "allowlist")
    if binary in HIGH_RISK_BINARIES:
        if _is_readonly_subcommand(binary, parts[1:]):
            return PolicyResult("allow", "low", "read-only subcommand of managed tool", f"readonly:{binary}")
        risk: RiskLevel = "high" if binary in {"rm", "dd", "mkfs", "reboot", "shutdown", "systemctl", "service"} else "medium"
        return PolicyResult("require_approval", risk, "command can change remote state", f"binary:{binary}")
    return PolicyResult("require_approval", "medium", "unrecognized command requires approval", "unknown_shell")


def _strip_sudo(parts: list[str]) -> list[str]:
    if parts and parts[0] == "sudo":
        while len(parts) > 1 and parts[1].startswith("-"):
            parts.pop(1)
        return parts[1:] or parts
    return parts


def _is_readonly_subcommand(binary: str, args: list[str]) -> bool:
    """Check if args for a high-risk binary form a read-only subcommand."""
    readonly_set = READONLY_SUBCOMMANDS.get(binary)
    if readonly_set is None:
        return False
    if not args:
        return False
    sub1 = args[0]
    # match original and destripped variants
    candidates = {sub1}
    if sub1.startswith("-"):
        candidates.add(sub1.lstrip("-"))
    if candidates & readonly_set:
        return True
    # check compound subcommands (e.g. docker container ls)
    if len(args) >= 2:
        sub2 = args[1]
        if binary == "docker":
            allowed_sub2 = DOCKER_READONLY_SUB2.get(sub1)
            return allowed_sub2 is not None and sub2 in allowed_sub2
        if binary == "kubectl":
            allowed_sub2 = KUBECTL_READONLY_SUB2.get(sub1)
            return allowed_sub2 is not None and sub2 in allowed_sub2
    return False


def _instruction_display(instruction: Instruction) -> str:
    if instruction.kind == "shell":
        return instruction.command or ""
    if instruction.kind in {"read_file", "sftp_get"}:
        return f"{instruction.kind} {instruction.remote_path or ''}"
    if instruction.kind in {"write_file", "sftp_put"}:
        content_note = ""
        if instruction.content is not None:
            content_note = f" content_length={len(instruction.content)}"
        method_note = ""
        if instruction.kind == "sftp_put":
            method_note = f" upload_method={instruction.upload_method}"
        return (
            f"{instruction.kind} {instruction.local_path or ''} -> "
            f"{instruction.remote_path or ''}{method_note}{content_note}"
        )
    return instruction.kind


def _redact_match(match: re.Match[str]) -> str:
    if match.lastindex and match.lastindex >= 3:
        return f"{match.group(1)}{match.group(2)}[REDACTED]"
    return "[REDACTED]"


def _redact_public_ipv4(match: re.Match[str]) -> str:
    value = match.group(0)
    try:
        address = ip_address(value)
    except ValueError:
        return value
    if address.version == 4 and address.is_global:
        return "[REDACTED_IP]"
    return value
