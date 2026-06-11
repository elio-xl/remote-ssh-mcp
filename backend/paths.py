from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "Remote SSH MCP"


def app_support_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APP_NAME
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME


def config_path() -> Path:
    return Path(os.environ.get("REMOTE_SSH_MCP_CONFIG_PATH", app_support_dir() / "ssh_config"))


def data_dir() -> Path:
    return Path(os.environ.get("REMOTE_SSH_MCP_DATA_DIR", app_support_dir() / "data"))
