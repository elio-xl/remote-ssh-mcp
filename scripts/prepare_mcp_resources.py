#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src-tauri" / "resources" / "mcp"


def copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
    )


def write_launcher() -> None:
    python_launcher = """#!/usr/bin/env python3
from __future__ import annotations

import runpy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

runpy.run_path(str(ROOT / "ssh_mcp_server.py"), run_name="__main__")
"""
    python_path = OUT / "run_mcp.py"
    python_path.write_text(python_launcher, encoding="utf-8")
    python_path.chmod(0o755)

    shell_launcher = """#!/bin/sh
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /usr/bin/python3 "$DIR/run_mcp.py"
"""
    shell_path = OUT / "remote-ssh-mcp-server"
    shell_path.write_text(shell_launcher, encoding="utf-8")
    shell_path.chmod(0o755)


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    shutil.copy2(ROOT / "ssh_mcp_server.py", OUT / "ssh_mcp_server.py")
    copy_tree(ROOT / "backend", OUT / "backend")
    write_launcher()


if __name__ == "__main__":
    main()
