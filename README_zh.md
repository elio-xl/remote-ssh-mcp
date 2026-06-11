# Remote SSH MCP

[English](README.md)

安全的 SSH 远程服务器管理工具，提供 MCP Server + 桌面 App + Claude Code Skill 三位一体的使用体验。

### 核心组件

| 组件 | 技术栈 | 说明 |
|---|---|---|
| **MCP Server** | Python 3.10+, paramiko | 通过 stdio 协议为 Claude Code 提供 SSH 远程操作能力 |
| **Web UI** | React 19, Vite, Tailwind, shadcn/ui | SSH 配置管理界面 |
| **Desktop App** | Tauri 2, Rust | 原生 macOS 桌面应用，集成配置管理和一键安装 |
| **Claude Skill** | Markdown + YAML frontmatter | AI 意图识别，自动触发 MCP 工具调用 |

## 功能特性

- **Plan / Approve / Execute / Audit 四阶段工作流** — 高风险操作必须创建计划并审批后才能执行，所有操作记录可审计
- **6 种指令类型** — shell（命令执行）、read_file / write_file（文件读写）、sftp_put / sftp_get（文件传输）
- **自动风险评估** — 策略引擎自动判定指令风险等级（low / medium / high）
- **敏感信息脱敏** — 支持自定义 redaction patterns，避免密钥等敏感信息出现在审计日志中
- **SSH 配置可视化管理** — 桌面 App 提供 GUI 管理 SSH Host 配置，支持连接测试
- **Claude Code 一键安装** — 桌面 App 可自动将 MCP Server 配置写入 Claude Code settings.json

## 快速开始

### 步骤一：使用桌面 App（推荐）

下载安装 macOS 桌面应用，开箱即用：

1. 下载最新版 DMG 安装包
2. 打开 Remote SSH MCP.app
3. 在 App 中添加 SSH 服务器配置
4. 点击「安装 MCP 配置」一键注册到 Claude Code
5. 在 Claude Code 中说 "帮我看看服务器磁盘使用情况"

### 步骤二：安装 Claude Code Skill

Skill 让 Claude 自动识别服务器操作意图，无需每次手动说明要使用 remote-ssh-mcp。

```bash
# 1. 克隆仓库
git clone https://github.com/elio-xl/remote-ssh-mcp.git
cd remote-ssh-mcp

# 2. 安装 Skill
mkdir -p ~/.claude/skills/remote-ssh
cp skills/remote-ssh/SKILL.md ~/.claude/skills/remote-ssh/
```

安装后，在 Claude Code 中说出以下任意关键词即可自动激活：

- **触发场景：** 连接服务器、查看线上日志、部署代码、重启服务、上传/下载文件、查看进程/磁盘/CPU
- **触发关键词：** 服务器、远程、SSH、线上、生产、部署、日志、运维、重启、连接、上传、下载

示例对话：

> "帮我看看 myserver 的磁盘使用情况"
> "查看线上 Nginx 错误日志"
> "部署最新代码到生产环境"

## 使用示例

### 查看服务器磁盘空间

Claude 自动调用 `remote_list_targets` 获取服务器列表，然后通过 `remote_run_instruction` 执行 `df -h` 命令，直接返回磁盘使用情况。

### 部署 Nginx 配置

Claude 自动走标准审批流：`remote_create_plan` → 展示计划详情 → `remote_approve_plan` → `remote_execute_plan` 执行上传配置和重载 Nginx → `remote_list_audit_events` 查看结果。

### 查看线上日志

Claude 直接调用 `remote_run_instruction`，执行 `tail -n 100 /var/log/nginx/error.log` 并返回日志内容。

## MCP Tools 参考

### 查询工具

| Tool | 说明 |
|---|---|
| `remote_list_targets` | 列出所有已配置的 SSH 目标 |
| `remote_get_capabilities` | 查看支持的指令类型和策略限制 |
| `remote_list_plans` | 列出执行计划 (可过滤 status) |
| `remote_get_plan` | 查看单个计划详情 |
| `remote_list_audit_events` | 查询审计日志 |

### 操作工具

| Tool | 说明 |
|---|---|
| `remote_preview_instruction` | 预览指令风险等级 |
| `remote_create_plan` | 创建执行计划 |
| `remote_approve_plan` | 批准计划 |
| `remote_reject_plan` | 拒绝计划 |
| `remote_execute_plan` | 执行计划 |
| `remote_run_instruction` | 直接执行低风险指令 |

### Instruction 类型

| 类型 | 风险 | 说明 |
|---|---|---|
| `shell` | low/medium | 执行 shell 命令 |
| `read_file` | low | 读取远程文件 |
| `sftp_get` | low | 下载文件 |
| `write_file` | high | 写入远程文件（需审批） |
| `sftp_put` | high | 上传文件（需审批） |


## 开发

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
