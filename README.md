# Remote SSH MCP

[中文版](README_zh.md)

A secure SSH remote server management toolkit, delivering MCP Server + Desktop App + Claude Code Skill in one package.

### Core Components

| Component | Stack | Description |
|---|---|---|
| **MCP Server** | Python 3.10+, paramiko | Provides Claude Code with SSH remote operations via the stdio protocol |
| **Web UI** | React 19, Vite, Tailwind, shadcn/ui | SSH configuration management interface |
| **Desktop App** | Tauri 2, Rust | Native macOS desktop app with config management and one-click setup |
| **Claude Skill** | Markdown + YAML frontmatter | AI intent detection that auto-triggers MCP tool invocations |

## Features

- **Plan / Approve / Execute / Audit workflow** — High-risk operations require a plan, approval, and execution; every action is auditable
- **6 instruction types** — shell (command execution), read_file / write_file (file I/O), sftp_put / sftp_get (file transfer)
- **Automatic risk assessment** — Policy engine classifies each instruction as low / medium / high risk
- **Sensitive data redaction** — Configurable redaction patterns keep secrets out of audit logs
- **Visual SSH config management** — Desktop app provides a GUI for managing SSH host entries with connection testing
- **One-click Claude Code setup** — Desktop app can auto-write the MCP server config into Claude Code's settings.json

## Quick Start

### Step 1: Desktop App (Recommended)

Download and install the macOS desktop app:

1. Download the latest DMG
2. Open Remote SSH MCP.app
3. Add your SSH server configurations in the app
4. Click "Install MCP Config" to register with Claude Code
5. In Claude Code, say "check disk usage on my server"

### Step 2: Install Claude Code Skill

The skill enables Claude to automatically recognize server-related requests — no need to mention "remote-ssh-mcp" every time.

```bash
# 1. Clone the repository
git clone https://github.com/elio-xl/remote-ssh-mcp.git
cd remote-ssh-mcp

# 2. Install the skill
mkdir -p ~/.claude/skills/remote-ssh
cp skills/remote-ssh/SKILL.md ~/.claude/skills/remote-ssh/
```

Once installed, any of the following triggers will activate the skill automatically:

- **Trigger scenarios:** connecting to servers, checking production logs, deploying code, restarting services, uploading/downloading files, checking processes/disk/CPU
- **Trigger keywords:** server, remote, SSH, production, deploy, logs, ops, restart, connect, upload, download

Example prompts:

> "Check disk usage on myserver"
> "Show me the Nginx error logs in production"
> "Deploy the latest code to staging"

## Usage Examples

### Check Disk Space

Claude automatically calls `remote_list_targets` to get available servers, then runs `df -h` via `remote_run_instruction` and returns the result.

### Deploy Nginx Config

Claude follows the approval workflow: `remote_create_plan` → presents the plan → `remote_approve_plan` → `remote_execute_plan` uploads config and reloads Nginx → `remote_list_audit_events` reviews the outcome.

### Inspect Production Logs

Claude calls `remote_run_instruction` directly to execute `tail -n 100 /var/log/nginx/error.log` and returns the log content.

## MCP Tools Reference

### Query Tools

| Tool | Description |
|---|---|
| `remote_list_targets` | List all configured SSH targets |
| `remote_get_capabilities` | View supported instruction types and policy limits |
| `remote_list_plans` | List execution plans (filterable by status) |
| `remote_get_plan` | Get plan details by ID |
| `remote_list_audit_events` | Query the audit log |

### Action Tools

| Tool | Description |
|---|---|
| `remote_preview_instruction` | Preview an instruction's risk level without executing |
| `remote_create_plan` | Create an execution plan |
| `remote_approve_plan` | Approve a pending plan |
| `remote_reject_plan` | Reject a pending plan |
| `remote_execute_plan` | Execute an approved plan |
| `remote_run_instruction` | Run a single low-risk instruction directly |

### Instruction Types

| Type | Risk | Description |
|---|---|---|
| `shell` | low/medium | Execute a shell command |
| `read_file` | low | Read a remote file |
| `sftp_get` | low | Download a file |
| `write_file` | high | Write to a remote file (requires approval) |
| `sftp_put` | high | Upload a file (requires approval) |


## Development

```bash
# Python MCP Server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python ssh_mcp_server.py

# Web UI
cd web
pnpm install
pnpm dev

# Desktop App (macOS)
pnpm tauri:dev
```

## License

MIT
