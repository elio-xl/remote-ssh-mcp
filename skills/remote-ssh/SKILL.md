---
name: remote-ssh
description: SSH 远程服务器管理 — 通过 MCP 工具执行远程命令、传输文件、管理 plan/approve/audit 工作流。适用于服务器运维、远程部署、日志查看、文件同步等场景。
---

# SSH 远程服务器管理

通过 remote-ssh-mcp 安全地操作远程 Linux 服务器。所有操作经过 plan（计划）→ approve（审批）→ execute（执行）→ audit（审计）四阶段工作流。

## When to Activate

**以下场景必须使用本 skill 的 MCP 工具，禁止用 Bash 执行或模拟任何远程操作：**

- 连接服务器 / SSH / 远程主机
- 查看服务器日志 / 线上日志 / 生产日志
- 服务器部署 / 远程部署 / 上线
- 服务器运维 / 重启服务 / 查看进程 / 磁盘 / CPU
- 远程执行命令 / 在服务器上运行脚本
- 上传/下载文件（替代 scp/sftp）
- 查看服务器状态（Docker/Nginx/MySQL/Redis 等）

**触发关键词：** 服务器、远程、SSH、线上、生产、部署、日志、运维、重启、连接、上传、下载

## MCP Tools

所有工具来自 `remote-ssh-mcp` MCP Server。

### 查询工具

| Tool | 用途 |
|---|---|
| `remote_list_targets` | 列出已配置的远程服务器 |
| `remote_get_capabilities` | 查看支持的指令类型和限制 |
| `remote_list_plans` | 列出执行计划，可选过滤 status |
| `remote_get_plan` | 查看单个计划详情 |
| `remote_list_audit_events` | 查询审计日志，可选过滤 plan_id/run_id/event_type |
| `remote_get_transfer` | 查询异步上传任务进度 |
| `remote_list_transfers` | 查询最近异步上传任务 |

### 操作工具（含审批流）

| Tool | 用途 |
|---|---|
| `remote_preview_instruction` | 预览指令风险等级，不实际执行 |
| `remote_create_plan` | 创建执行计划，自动评估风险 |
| `remote_approve_plan` | 批准计划 |
| `remote_reject_plan` | 拒绝计划 |
| `remote_execute_plan` | 执行已批准计划 |
| `remote_run_instruction` | 直接执行低风险指令 |
| `remote_start_transfer` | 启动已批准上传 plan step，立即返回 transfer_id |
| `remote_cancel_transfer` | 请求取消 pending/running 上传任务 |

## 快速调用 MCP

触发本 skill 后，优先直接调用 MCP 工具，不要先用 Bash 做环境检查、不要手工启动 MCP Server、不要解释工具调用流程后再行动。

### 决策顺序

1. **先判断目标服务器是否明确**
   - 用户已给出明确别名：直接使用该别名调用后续工具
   - 用户未给出别名或别名不确定：立即调用 `remote_list_targets`
2. **再判断操作风险**
   - 只读 shell、查看状态、查看日志、读取文件、下载文件：优先使用 `remote_run_instruction`
   - 写文件、上传文件、重启服务、部署、删除、修改配置：使用 `remote_create_plan` 进入审批流
3. **执行后按需查看审计**
   - 用户只要结果：直接返回工具结果中的 stdout/stderr 摘要
   - 需要排查失败或确认执行记录：调用 `remote_list_audit_events`

### 最快路径示例

查看磁盘、CPU、进程、日志等低风险请求：

```
remote_list_targets（仅当目标不明确） → remote_run_instruction
```

明确目标别名且是低风险请求：

```
remote_run_instruction
```

部署、写配置等高风险请求：

```
remote_list_targets（仅当目标不明确） → remote_create_plan → 等待用户确认 → remote_approve_plan → remote_execute_plan
```

上传文件必须使用异步 transfer 流程：

```
remote_list_targets（仅当目标不明确） → remote_create_plan → 等待用户确认 → remote_approve_plan → remote_start_transfer → remote_get_transfer
```

启动后立即告诉用户 `transfer_id`、`local_path_display`、`remote_path`、`target_alias`、`bytes_total`、`conflict_policy`。上传未完成时每 60 秒调用 `remote_get_transfer` 并报告 `percent`、`bytes_per_second`、`eta_seconds`。用户要求停止上传时调用 `remote_cancel_transfer`，不要尝试用 Bash 终止进程。完成后报告 `actual_remote_path`、`remote_sha256`、`elapsed_seconds`、`backup_remote_path`。

### 禁止绕路

- 不要用 Bash 检查 MCP 是否可用
- 不要用 Bash 构造 JSON-RPC 请求
- 不要用 Bash 执行 `/Applications/Remote SSH MCP.app/.../remote-ssh-mcp-server`
- 不要读取 `~/.ssh/config` 或项目 `ssh_config` 来猜服务器
- MCP 工具不可见时，直接告知“当前 session 未暴露 remote-ssh-mcp 工具，需要重启 Claude Code 或检查 MCP 配置”，不要改用 Bash

## Workflow

### 标准流程（高风险操作）

```
remote_list_targets → remote_create_plan → remote_approve_plan → remote_execute_plan → remote_list_audit_events
```

### 上传流程（高风险操作）

```
remote_list_targets → remote_create_plan → remote_approve_plan → remote_start_transfer → remote_get_transfer
```

### 快速流程（低风险操作）

```
remote_list_targets → remote_run_instruction
```

- shell（只读命令）、read_file、sftp_get 通常可直接执行
- write_file、sftp_put 会被要求走审批流程

## Instruction 格式

```json
// shell 命令
{ "kind": "shell", "command": "df -h", "workdir": "/tmp", "timeout_seconds": 30 }

// 读取远程文件
{ "kind": "read_file", "remote_path": "/var/log/nginx/access.log" }

// 写入远程文件（自动备份）
{ "kind": "write_file", "remote_path": "/etc/nginx/conf.d/app.conf", "content": "server { ... }", "create_backup": true }

// 上传文件
{ "kind": "sftp_put", "local_path": "./deploy.tar.gz", "remote_path": "/opt/app/deploy.tar.gz" }

// 下载文件
{ "kind": "sftp_get", "remote_path": "/opt/app/config.yaml", "local_path": "./config.yaml" }
```

### 风险等级

| 指令 | 风险 | 策略 |
|---|---|---|
| `shell` (只读) | low | 直接执行 |
| `read_file` | low | 直接执行 |
| `sftp_get` | low | 直接执行 |
| `shell` (写操作) | medium | 需预览确认 |
| `write_file` | high | 需创建 plan 审批 |
| `sftp_put` | high | 需创建 plan 审批 |

## 关键规则

1. **始终先调 `remote_list_targets`** 获取 target_alias，不要猜测服务器名
2. `remote_create_plan` 必填 `target_alias`、`goal`、`instructions`
3. `remote_approve_plan` 建议传入 `plan_hash` 防篡改
4. 执行后通过 `remote_list_audit_events` 查看 stdout/stderr
5. 上传文件时必须在审批后调用 `remote_start_transfer`，不要用 `remote_execute_plan` 等待大文件同步上传
6. 上传启动后必须通过 `remote_get_transfer` 轮询；用户要求停止时调用 `remote_cancel_transfer`
7. **禁止从本机直接连接服务器** — 严禁使用 Bash 执行任何 SSH 连接命令，包括但不限于：
   - `ssh gw`、`ssh user@host`、`ssh -i key user@host`
   - `scp`、`sftp`、`rsync -e ssh` 等基于 SSH 的传输命令
   - 任何通过 `~/.ssh/config` 中 Host 别名建立的连接
   所有远程操作必须通过 `remote-ssh-mcp` 的 MCP 工具完成
8. **禁止用 Bash 手工调用 MCP Server** — 严禁通过 Bash 启动 `/Applications/Remote SSH MCP.app/.../remote-ssh-mcp-server`、设置 `MCP=...`/`REQUEST=...`、拼接 JSON-RPC、`echo`/`printf` 管道等方式模拟 MCP 工具调用。必须直接使用会话中暴露的 MCP 工具，例如 `remote_list_targets`、`remote_run_instruction`、`remote_create_plan`。
9. **禁止读取 SSH 配置文件** — 不得用任何方式（cat、read、Bash 等）读取以下敏感文件：
   - `~/.ssh/config`、`/etc/ssh/ssh_config` 等 SSH 客户端配置
   - 项目中的 `ssh_config`、`*.pem`、`*.key` 等包含私钥或公网 IP 的文件
   服务器信息只能通过 `remote_list_targets` 获取
