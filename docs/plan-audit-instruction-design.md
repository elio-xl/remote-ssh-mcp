# Plan、审计、指令设计文档

## 1. 背景

当前 `backend/ssh/models.py` 已经定义了 SSH 基础设施层模型：

- `ConnectionTarget`: 描述 SSH 连接目标。
- `SSHPoolConfig`: 描述连接池配置。
- `PooledSSHConnection`: 描述池化连接运行态。
- SSH 连接、超时、断开等错误类型。

这些模型的职责是连接生命周期、连接池调度和 SSH 执行基础设施，不应承载 Plan、审批、审计和指令语义。

Plan、审计、指令属于远程操作编排层。它们应建立在 SSH 执行能力之上，调用 `backend/ssh/executor.py` 和 `backend/ssh/pool.py`，但不反向污染 SSH 基础设施层。

## 2. 目标

本设计用于定义远程操作的三类核心领域对象：

| 对象 | 职责 |
| --- | --- |
| Plan | 描述一次远程操作计划，包括目标、步骤、风险、审批要求。 |
| Instruction | 描述一个最小可执行动作，例如 shell 命令、文件上传、文件下载。 |
| Audit | 记录计划、审批、执行、安全拦截和结果，用于追踪和问责。 |

设计目标：

- 支持 plan-and-approve 工作流。
- 支持直接执行低风险只读指令。
- 支持高风险操作审批。
- 支持完整审计链路。
- 支持敏感信息脱敏。
- 保持 SSH 连接池职责单一。
- 为后续 MCP tool、Web UI、CLI 复用同一领域模型。

## 3. 非目标

本设计不处理以下内容：

- SSH 连接建立、保活、重连和连接池调度。
- Paramiko channel 细节。
- 凭证加密存储。
- Web UI 展示细节。
- MCP 协议编解码。
- 分布式任务队列。
- 多进程共享 SSH 活连接。

这些职责应分别由 `backend/ssh/`、凭证服务、API 层或未来任务队列模块处理。

## 4. 分层设计

推荐模块结构：

```text
backend/
  ssh/
    models.py          # SSH 基础设施模型
    pool.py            # SSHConnectionPool
    executor.py        # exec_command
    sftp.py            # SFTP 操作

  remote/
    models.py          # Plan、Instruction、Audit、Run 模型
    policy.py          # 风险判断、allowlist、blocklist、审批规则
    runner.py          # 执行 Plan 和 Instruction
    audit_store.py     # 审计事件持久化
    plan_store.py      # Plan 持久化
```

依赖方向：

```text
API / MCP tools / Web UI
        ↓
remote planner / runner / policy / audit
        ↓
ssh pool / executor / sftp
        ↓
paramiko
```

约束：

- `backend/ssh/models.py` 不依赖 `backend/remote/`。
- `remote.runner` 可以依赖 `ssh.pool` 和 `ssh.executor`。
- `remote.models` 不保存明文密码、私钥内容或 Paramiko 对象。
- Plan 和 Audit 使用 `target_alias` 或 `target_key` 引用目标，不直接持有 `PooledSSHConnection`。

## 5. Plan 设计

### 5.1 职责

Plan 描述“将要做什么”，用于审批、预览、执行和审计。

Plan 不应描述“当前执行到哪一步”。执行进度应由 Run 模型描述。

### 5.2 数据模型

```python
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal


PlanStatus = Literal[
    "draft",
    "pending_approval",
    "approved",
    "rejected",
    "expired",
    "executed",
]

RiskLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class ExecutionPlan:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    target_alias: str = ""
    goal: str = ""
    summary: str = ""
    steps: list[PlanStep] = field(default_factory=list)
    risk_level: RiskLevel = "low"
    status: PlanStatus = "draft"
    requires_approval: bool = False
    created_by: str = "system"
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanStep:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    description: str = ""
    instruction: Instruction | None = None
    expected_effect: str = ""
    rollback_hint: str | None = None
    risk_level: RiskLevel = "low"
```

### 5.3 字段说明

| 字段 | 说明 |
| --- | --- |
| `id` | Plan 唯一标识，用于审批、执行和审计关联。 |
| `target_alias` | 目标 SSH 配置别名，不存储凭证。 |
| `goal` | 用户意图，例如“重启 nginx”。 |
| `summary` | 给人阅读的计划摘要。 |
| `steps` | 计划步骤，每步绑定一个 Instruction。 |
| `risk_level` | 整体风险等级，通常取所有步骤的最高风险。 |
| `status` | Plan 生命周期状态。 |
| `requires_approval` | 是否需要人工审批。 |
| `created_by` | 创建者，可为 MCP client、用户 ID 或 system。 |
| `expires_at` | 过期时间，防止旧计划被误执行。 |
| `metadata` | 非关键扩展信息。 |

### 5.4 状态流转

```text
draft
  ↓
pending_approval ──→ rejected
  ↓
approved ──→ expired
  ↓
executed
```

规则：

- 低风险、allowlist 内的只读操作可以不创建待审批 Plan，直接执行并审计。
- 中高风险操作必须进入 `pending_approval`。
- `approved` 后才能执行。
- 过期 Plan 不允许执行。
- 已执行 Plan 不允许重复执行，除非显式复制为新 Plan。

### 5.5 Plan 边界

Plan 应避免包含：

- 明文密码。
- 私钥内容。
- Paramiko client 或 channel。
- 大段 stdout/stderr。
- 执行进度。

Plan 应包含：

- 用户可理解的目标和步骤。
- 每步将执行的指令预览。
- 风险等级。
- 预期影响。
- 回滚提示。

## 6. Instruction 设计

### 6.1 职责

Instruction 是最小可执行动作。它是 runner 的输入，也是风险判断和审计的核心对象。

不要使用裸字符串命令作为系统内部唯一表示。裸字符串无法稳定表达超时、工作目录、stdin、SFTP、风险和脱敏规则。

### 6.2 指令类型

推荐指令类型：

| 类型 | 说明 |
| --- | --- |
| `shell` | 执行 shell 命令。 |
| `sftp_put` | 上传本地文件到远端。 |
| `sftp_get` | 下载远端文件到本地。 |
| `read_file` | 读取远端文件。 |
| `write_file` | 写入远端文件，通常需要备份和审批。 |
| `interactive` | 交互式会话，默认高风险。 |

### 6.3 数据模型

```python
InstructionKind = Literal[
    "shell",
    "sftp_put",
    "sftp_get",
    "read_file",
    "write_file",
    "interactive",
]


@dataclass(frozen=True)
class Instruction:
    kind: InstructionKind
    command: str | None = None
    workdir: str = ""
    timeout_seconds: int = 60
    stdin: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    local_path: str | None = None
    remote_path: str | None = None
    content: str | None = None
    create_backup: bool = True
    redaction_patterns: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 6.4 Shell 指令规则

`shell` 指令必须满足：

- `command` 非空。
- `timeout_seconds` 必须为正整数。
- `workdir` 只作为工作目录，不参与风险判断绕过。
- 执行前必须经过 policy 检查。
- 输出必须经过审计脱敏策略处理。

示例：

```python
Instruction(
    kind="shell",
    command="systemctl status nginx --no-pager",
    workdir="/",
    timeout_seconds=30,
)
```

### 6.5 文件类指令规则

`read_file`：

- 默认低到中风险，取决于路径。
- 读取 `/etc/shadow`、私钥、credential 文件应阻断或要求审批。

`write_file`：

- 默认中高风险。
- 默认 `create_backup=True`。
- 必须记录目标路径和内容摘要。
- 不建议在审计中保存完整内容，除非明确配置允许。

`sftp_put` / `sftp_get`：

- 必须校验 `local_path` 和 `remote_path`。
- 对覆盖远端文件的上传默认需要审批。
- 对下载敏感路径默认需要审批或阻断。

### 6.6 指令预览

Instruction 应提供安全预览，用于 Plan 展示和审计：

```python
@dataclass(frozen=True)
class InstructionPreview:
    kind: InstructionKind
    display: str
    risk_level: RiskLevel
    redacted: bool = False
```

预览规则：

- 明文 token、password、secret 必须脱敏。
- 文件内容默认只展示摘要和长度。
- shell 命令可展示完整命令，但需应用脱敏规则。

## 7. 审计设计

### 7.1 职责

审计记录系统中发生过的关键事件。审计不是普通日志，不能只用于调试。

审计必须回答以下问题：

- 谁发起了操作。
- 对哪个目标执行。
- 系统计划做什么。
- 谁批准了计划。
- 实际执行了什么。
- 执行结果如何。
- 是否发生安全拦截或脱敏。

### 7.2 审计事件类型

```python
AuditEventType = Literal[
    "plan_created",
    "approval_requested",
    "approval_granted",
    "approval_rejected",
    "plan_expired",
    "run_started",
    "step_started",
    "step_finished",
    "step_failed",
    "instruction_blocked",
    "run_finished",
    "run_failed",
]
```

### 7.3 数据模型

```python
@dataclass(frozen=True)
class AuditEvent:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    event_type: AuditEventType = "run_started"
    timestamp: float = field(default_factory=time.time)
    actor: str = "system"
    target_alias: str = ""
    plan_id: str | None = None
    run_id: str | None = None
    step_id: str | None = None
    instruction_kind: InstructionKind | None = None
    instruction_preview: str | None = None
    risk_level: RiskLevel | None = None
    decision: str | None = None
    exit_code: int | None = None
    elapsed_seconds: float | None = None
    stdout_digest: str | None = None
    stderr_digest: str | None = None
    stdout_excerpt: str | None = None
    stderr_excerpt: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 7.4 审计字段说明

| 字段 | 说明 |
| --- | --- |
| `id` | 审计事件唯一 ID。 |
| `event_type` | 事件类型。 |
| `timestamp` | 事件发生时间。 |
| `actor` | 操作者或系统组件。 |
| `target_alias` | 目标服务器别名。 |
| `plan_id` | 关联 Plan。 |
| `run_id` | 关联执行实例。 |
| `step_id` | 关联 PlanStep。 |
| `instruction_preview` | 脱敏后的指令预览。 |
| `risk_level` | 风险等级。 |
| `decision` | 审批或策略决策。 |
| `exit_code` | shell 命令退出码。 |
| `stdout_digest` | stdout 摘要，例如 sha256。 |
| `stderr_digest` | stderr 摘要，例如 sha256。 |
| `stdout_excerpt` | stdout 脱敏截断片段。 |
| `stderr_excerpt` | stderr 脱敏截断片段。 |
| `error_type` | 错误类型，例如 timeout、connection_broken。 |
| `metadata` | 扩展字段。 |

### 7.5 审计存储规则

审计存储必须满足：

- append-only。
- 不覆盖旧事件。
- 不保存明文密码、token、私钥内容。
- 输出默认截断。
- 敏感输出默认只保存摘要。
- 写入失败时不能静默吞掉，至少应返回给调用方或进入错误日志。

推荐最小持久化格式：JSON Lines。

```jsonl
{"id":"evt_1","event_type":"plan_created","plan_id":"plan_1","target_alias":"prod-1"}
{"id":"evt_2","event_type":"approval_granted","plan_id":"plan_1","actor":"user"}
{"id":"evt_3","event_type":"step_finished","run_id":"run_1","exit_code":0}
```

后续可迁移到 SQLite，但模型和事件语义不应依赖具体存储实现。

## 8. Run 设计

Plan 是静态计划，Run 是一次执行实例。

### 8.1 数据模型

```python
RunStatus = Literal[
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
]


@dataclass
class ExecutionRun:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    plan_id: str | None = None
    target_alias: str = ""
    status: RunStatus = "running"
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    current_step_id: str | None = None
    step_results: list[StepResult] = field(default_factory=list)


@dataclass(frozen=True)
class StepResult:
    step_id: str
    instruction_kind: InstructionKind
    status: RunStatus
    exit_code: int | None = None
    elapsed_seconds: float | None = None
    stdout_digest: str | None = None
    stderr_digest: str | None = None
    error_message: str | None = None
```

### 8.2 Run 规则

- 一次 Plan 可以产生一个或多个 Run，但默认不允许重复执行同一个已执行 Plan。
- Run 开始、每步开始、每步结束、Run 结束都必须写审计。
- 任一步失败时，默认停止后续步骤。
- 是否继续执行应由 Plan 或 runner 参数显式决定。

## 9. Policy 设计

Policy 负责判断指令是否允许直接执行、需要审批或必须阻断。

### 9.1 决策结果

```python
PolicyDecision = Literal["allow", "require_approval", "block"]


@dataclass(frozen=True)
class PolicyResult:
    decision: PolicyDecision
    risk_level: RiskLevel
    reason: str
    matched_rule: str | None = None
```

### 9.2 基础规则

建议初始规则：

| 场景 | 决策 |
| --- | --- |
| `pwd`、`whoami`、`ls` 等只读 allowlist | `allow` |
| `cat` 普通路径 | `allow` 或 `require_approval` |
| `systemctl restart` | `require_approval` |
| `rm -rf` | `require_approval` 或 `block` |
| 修改 `/etc/ssh/sshd_config` | `require_approval` |
| 读取私钥、token、shadow 文件 | `block` 或 `require_approval` |
| 交互式 shell | `require_approval` |
| 未识别复杂 shell | `require_approval` |

### 9.3 风险等级

| 等级 | 含义 |
| --- | --- |
| `low` | 只读、可重复、影响小。 |
| `medium` | 可能读取敏感信息或影响服务状态。 |
| `high` | 修改系统状态、删除数据、重启服务、变更权限或网络策略。 |

## 10. 执行流程

### 10.1 直接执行流程

```text
1. API/MCP 收到用户请求。
2. 构造 Instruction。
3. policy 评估为 allow。
4. 写 audit: run_started。
5. runner 获取 SSH 连接。
6. 调用 exec_command 或 sftp 操作。
7. 写 audit: step_finished / run_finished。
8. 返回结果。
```

### 10.2 Plan 审批流程

```text
1. API/MCP 收到用户请求。
2. 构造 Instruction。
3. policy 评估为 require_approval。
4. 创建 ExecutionPlan，状态 pending_approval。
5. 写 audit: plan_created、approval_requested。
6. 用户审批。
7. 写 audit: approval_granted 或 approval_rejected。
8. approved 后创建 ExecutionRun。
9. runner 按步骤执行。
10. 每步写审计。
11. Run 结束写审计。
```

### 10.3 阻断流程

```text
1. 构造 Instruction。
2. policy 评估为 block。
3. 写 audit: instruction_blocked。
4. 返回阻断原因。
5. 不创建 SSH channel，不执行远程操作。
```

## 11. 与现有 SSH 模型的关系

现有 `backend/ssh/models.py` 可以保持不变。

建议职责划分：

| 模块 | 保留/新增职责 |
| --- | --- |
| `backend/ssh/models.py` | `ConnectionTarget`、`SSHPoolConfig`、`PooledSSHConnection`、SSH 错误。 |
| `backend/ssh/pool.py` | 连接获取、释放、健康检查、空闲回收。 |
| `backend/ssh/executor.py` | 执行 shell 命令并返回 `CommandResult`。 |
| `backend/remote/models.py` | `ExecutionPlan`、`PlanStep`、`Instruction`、`AuditEvent`、`ExecutionRun`。 |
| `backend/remote/policy.py` | allowlist、blocklist、风险判断、审批判断。 |
| `backend/remote/runner.py` | 将 Instruction 映射到底层 SSH/SFTP 操作。 |
| `backend/remote/audit_store.py` | 审计事件落盘和查询。 |

关键点：

- Plan 不应直接持有 `PooledSSHConnection`。
- Audit 不应记录 `ConnectionTarget.password`。
- Instruction 不应绕过 policy 直接调用 executor。
- executor 不应知道 Plan 和 Audit 的存在。

## 12. 安全要求

### 12.1 敏感信息

以下内容不得明文进入 Plan 或 Audit：

- SSH 密码。
- 私钥内容。
- 私钥 passphrase。
- API token。
- Cookie。
- `.env` 中的 secret。
- 远端 credential 文件内容。

### 12.2 输出处理

命令输出处理规则：

- 默认保存 digest。
- 默认保存截断后的 excerpt。
- excerpt 必须先脱敏再存储。
- 完整输出如需保存，应作为 artifact，并明确标记访问权限。

### 12.3 审批一致性

审批对象必须是不可变 Plan。

如果审批后修改了 Instruction、target 或 steps，必须生成新 Plan 并重新审批。

## 13. 最小可落地版本

第一阶段只需要支持 shell 指令：

```text
backend/remote/models.py
  - Instruction
  - PlanStep
  - ExecutionPlan
  - AuditEvent
  - ExecutionRun

backend/remote/policy.py
  - classify_instruction
  - redact_text

backend/remote/audit_store.py
  - append_event
  - list_events

backend/remote/runner.py
  - run_instruction
  - run_plan
```

第一阶段可暂不支持：

- SQLite。
- 异步任务队列。
- 复杂回滚。
- 交互式 shell。
- 完整 artifact 管理。

但第一阶段必须支持：

- 低风险直接执行。
- 高风险生成 Plan。
- Plan 审批后执行。
- 审计事件落盘。
- 指令预览脱敏。
- stdout/stderr 摘要和截断。

## 14. 验收标准

- `backend/ssh/models.py` 不引入 Plan、Audit、Instruction。
- 一个非 allowlist shell 命令会生成待审批 Plan。
- 一个 approved Plan 可以被 runner 执行。
- 每次执行至少产生 `run_started`、`step_started`、`step_finished`、`run_finished` 审计事件。
- 失败和超时也有审计事件。
- 审计中不出现密码、私钥、passphrase。
- Plan 过期后不能执行。
- 审批后的 Plan 不可被原地修改。

## 15. MCP 层设计

### 15.1 设计定位

MCP 层是远程操作系统的协议适配层，不是业务规则层。

MCP tool handler 只负责：

- 接收 MCP client 传入的结构化参数。
- 做最基础的参数形状校验。
- 构造领域对象，例如 `Instruction`。
- 调用 `remote.policy`、`remote.plan_store`、`remote.runner`、`remote.audit_store`。
- 返回适合 LLM 和 MCP client 消费的结构化结果。

MCP tool handler 不负责：

- 判断命令是否危险。
- 拼接 shell 审批文案。
- 直接调用 SSH executor 执行高风险命令。
- 直接读写审计文件格式。
- 保存明文凭证。
- 绕过 Plan 执行远程修改。

推荐调用链：

```text
MCP tool handler
  ↓
RemoteApplicationService
  ↓
InstructionFactory / PolicyEngine / PlanStore / AuditStore / Runner
  ↓
SSHConnectionPool / SSHExecutor / SFTP
```

### 15.2 MCP 设计原则

- Tool 名称面向能力，不面向内部实现细节。
- Tool 输入必须稳定，避免让模型自由拼接内部 JSON。
- Tool 输出必须同时适合人读和机器继续调用。
- 每个会改变远端状态的 tool 都必须经过 `Instruction -> Policy -> Plan -> Approval -> Runner`。
- 低风险只读操作可以直接执行，但仍必须写审计。
- 高风险操作必须返回 Plan，不执行。
- 审批和执行必须拆成两个 tool。
- 执行 tool 必须重新校验 Plan 状态、过期时间和内容哈希。
- MCP 层不能信任 client 声称的风险等级，风险等级只能由服务端 policy 计算。

### 15.3 Tool 分组

推荐把 MCP tools 分为 6 组：

| 分组 | 职责 |
| --- | --- |
| Target tools | 管理和选择远程目标。 |
| Instruction tools | 创建或预检指令。 |
| Plan tools | 创建、查看、审批、拒绝计划。 |
| Run tools | 执行计划、查看执行结果。 |
| Audit tools | 查询审计事件。 |
| Capability tools | 暴露服务端策略、限制和能力。 |

第一阶段可以只实现 Plan tools、Run tools 和 Audit tools。Target tools 可以复用现有 SSH 配置服务。

## 16. MCP Tool 清单

### 16.1 Target Tools

#### `remote_list_targets`

列出可用远程目标。

输入：

```json
{}
```

输出：

```json
{
  "success": true,
  "targets": [
    {
      "alias": "dev-1",
      "host_display": "192.168.*.*",
      "username": "ubuntu",
      "auth_type": "key",
      "has_jump_host": false
    }
  ]
}
```

约束：

- 不返回密码。
- 不返回私钥内容。
- 不返回真实 IP、hostname 或端口。
- 如需展示目标地址，只返回脱敏后的 `host_display`。
- 私钥路径是否返回取决于产品安全策略，默认可不返回。

#### `remote_check_target`

检查目标连通性。

输入：

```json
{
  "target_alias": "dev-1"
}
```

输出：

```json
{
  "success": true,
  "target_alias": "dev-1",
  "reachable": true,
  "host_display": "192.168.*.*",
  "latency_ms": 120,
  "message": "target is reachable"
}
```

### 16.2 Instruction Tools

#### `remote_preview_instruction`

创建指令预览，但不创建 Plan，也不执行。

输入：

```json
{
  "target_alias": "dev-1",
  "instruction": {
    "kind": "shell",
    "command": "systemctl restart nginx",
    "workdir": "/",
    "timeout_seconds": 60
  }
}
```

输出：

```json
{
  "success": true,
  "target_alias": "dev-1",
  "instruction_preview": "systemctl restart nginx",
  "policy": {
    "decision": "require_approval",
    "risk_level": "high",
    "reason": "service restart changes remote runtime state"
  }
}
```

用途：

- 给 UI 或 MCP client 做执行前预检。
- 帮助模型理解为什么某个操作需要审批。
- 不产生可执行 Plan。

### 16.3 Plan Tools

#### `remote_create_plan`

从一个或多个 instruction 创建 Plan。

输入：

```json
{
  "target_alias": "dev-1",
  "goal": "restart nginx after config update",
  "instructions": [
    {
      "kind": "shell",
      "command": "nginx -t",
      "workdir": "/",
      "timeout_seconds": 30
    },
    {
      "kind": "shell",
      "command": "systemctl restart nginx",
      "workdir": "/",
      "timeout_seconds": 60
    }
  ]
}
```

输出：

```json
{
  "success": true,
  "plan": {
    "id": "plan_01",
    "target_alias": "dev-1",
    "goal": "restart nginx after config update",
    "summary": "Validate nginx config and restart nginx service.",
    "status": "pending_approval",
    "risk_level": "high",
    "requires_approval": true,
    "plan_hash": "sha256:abc123",
    "expires_at": 1710000000,
    "steps": [
      {
        "id": "step_01",
        "title": "Validate nginx config",
        "instruction_preview": "nginx -t",
        "risk_level": "low",
        "expected_effect": "nginx config is validated without applying changes"
      },
      {
        "id": "step_02",
        "title": "Restart nginx",
        "instruction_preview": "systemctl restart nginx",
        "risk_level": "high",
        "expected_effect": "nginx service restarts and active connections may be affected",
        "rollback_hint": "check service status and restore previous config if restart fails"
      }
    ]
  }
}
```

规则：

- MCP client 不能传入 `risk_level` 覆盖服务端判断。
- 服务端必须为 Plan 计算 `plan_hash`。
- Plan 创建后必须写 `plan_created` 审计事件。
- 如果所有 instruction 都是低风险，服务端仍可创建 Plan，但也可以提示可直接执行。

#### `remote_get_plan`

查询 Plan 详情。

输入：

```json
{
  "plan_id": "plan_01"
}
```

输出：

```json
{
  "success": true,
  "plan": {
    "id": "plan_01",
    "status": "pending_approval",
    "risk_level": "high",
    "plan_hash": "sha256:abc123",
    "summary": "Validate nginx config and restart nginx service.",
    "steps": []
  }
}
```

#### `remote_list_plans`

查询 Plan 列表。

输入：

```json
{
  "target_alias": "dev-1",
  "status": "pending_approval",
  "limit": 20
}
```

输出：

```json
{
  "success": true,
  "plans": [
    {
      "id": "plan_01",
      "target_alias": "dev-1",
      "status": "pending_approval",
      "risk_level": "high",
      "summary": "Validate nginx config and restart nginx service.",
      "created_at": 1710000000,
      "expires_at": 1710086400
    }
  ]
}
```

#### `remote_approve_plan`

审批 Plan。

输入：

```json
{
  "plan_id": "plan_01",
  "plan_hash": "sha256:abc123",
  "approved_by": "user",
  "comment": "approved for maintenance window"
}
```

输出：

```json
{
  "success": true,
  "plan_id": "plan_01",
  "status": "approved",
  "approved_by": "user",
  "approved_at": 1710000300
}
```

规则：

- `plan_hash` 必须匹配当前存储的 Plan。
- Plan 已过期时不能审批。
- 已拒绝或已执行的 Plan 不能审批。
- 审批成功必须写 `approval_granted` 审计事件。

#### `remote_reject_plan`

拒绝 Plan。

输入：

```json
{
  "plan_id": "plan_01",
  "rejected_by": "user",
  "reason": "not in maintenance window"
}
```

输出：

```json
{
  "success": true,
  "plan_id": "plan_01",
  "status": "rejected"
}
```

### 16.4 Run Tools

#### `remote_execute_plan`

执行已审批 Plan。

输入：

```json
{
  "plan_id": "plan_01",
  "plan_hash": "sha256:abc123"
}
```

输出：

```json
{
  "success": true,
  "plan_id": "plan_01",
  "run_id": "run_01",
  "status": "succeeded",
  "results": [
    {
      "step_id": "step_01",
      "status": "succeeded",
      "exit_code": 0,
      "elapsed_seconds": 0.32,
      "stdout_excerpt": "syntax is ok",
      "stderr_excerpt": ""
    }
  ]
}
```

规则：

- 必须重新加载 Plan。
- 必须校验 Plan 状态为 `approved`。
- 必须校验 `plan_hash`。
- 必须校验 Plan 未过期。
- 执行前写 `run_started`。
- 每步写 `step_started` 和 `step_finished` 或 `step_failed`。
- 执行完成写 `run_finished` 或 `run_failed`。

#### `remote_run_instruction`

直接执行单条低风险 instruction。

输入：

```json
{
  "target_alias": "dev-1",
  "instruction": {
    "kind": "shell",
    "command": "whoami",
    "workdir": "/",
    "timeout_seconds": 10
  }
}
```

低风险输出：

```json
{
  "success": true,
  "run_id": "run_02",
  "status": "succeeded",
  "policy": {
    "decision": "allow",
    "risk_level": "low"
  },
  "result": {
    "exit_code": 0,
    "stdout_excerpt": "ubuntu",
    "stderr_excerpt": "",
    "elapsed_seconds": 0.08
  }
}
```

高风险输出：

```json
{
  "success": false,
  "requires_plan": true,
  "policy": {
    "decision": "require_approval",
    "risk_level": "high",
    "reason": "instruction changes remote service state"
  },
  "message": "Create and approve a plan before executing this instruction."
}
```

规则：

- 该 tool 只能执行 policy 决策为 `allow` 的指令。
- 如果 policy 返回 `require_approval`，必须拒绝执行。
- 如果 policy 返回 `block`，必须写 `instruction_blocked` 审计。

#### `remote_get_run`

查询执行实例。

输入：

```json
{
  "run_id": "run_01"
}
```

输出：

```json
{
  "success": true,
  "run": {
    "id": "run_01",
    "plan_id": "plan_01",
    "target_alias": "dev-1",
    "status": "succeeded",
    "started_at": 1710000400,
    "finished_at": 1710000402,
    "step_results": []
  }
}
```

### 16.5 Audit Tools

#### `remote_list_audit_events`

查询审计事件。

输入：

```json
{
  "target_alias": "dev-1",
  "plan_id": "plan_01",
  "run_id": "run_01",
  "limit": 50
}
```

输出：

```json
{
  "success": true,
  "events": [
    {
      "id": "evt_01",
      "event_type": "plan_created",
      "timestamp": 1710000000,
      "actor": "mcp-client",
      "target_alias": "dev-1",
      "plan_id": "plan_01",
      "risk_level": "high",
      "instruction_preview": "systemctl restart nginx"
    }
  ]
}
```

规则：

- 默认不返回完整 stdout/stderr。
- 默认不返回敏感 metadata。
- 支持按 `plan_id`、`run_id`、`target_alias` 过滤。

### 16.6 Capability Tools

#### `remote_get_capabilities`

暴露服务端支持的指令类型、策略限制和输出限制。

输入：

```json
{}
```

输出：

```json
{
  "success": true,
  "instruction_kinds": ["shell", "read_file", "write_file", "sftp_put", "sftp_get"],
  "direct_run_policy": {
    "supports_direct_low_risk": true,
    "requires_plan_for_medium_risk": true,
    "requires_plan_for_high_risk": true
  },
  "limits": {
    "max_steps_per_plan": 20,
    "default_plan_ttl_seconds": 86400,
    "stdout_excerpt_bytes": 8192,
    "stderr_excerpt_bytes": 8192
  }
}
```

用途：

- 让 MCP client 和 LLM 明确服务端能力。
- 减少模型猜测 tool 行为。
- 为不同部署环境暴露不同限制。

## 17. MCP 返回协议

### 17.1 通用返回字段

所有 MCP tool 建议返回统一结构：

```json
{
  "success": true,
  "message": "human readable summary",
  "data": {},
  "error": null
}
```

失败返回：

```json
{
  "success": false,
  "message": "failed to execute instruction",
  "data": {},
  "error": {
    "code": "POLICY_REQUIRES_APPROVAL",
    "detail": "instruction changes remote state",
    "retryable": false
  }
}
```

为了方便 LLM 使用，关键字段也可以提升到顶层，例如：

```json
{
  "success": false,
  "requires_plan": true,
  "risk_level": "high",
  "message": "approval is required before execution"
}
```

### 17.2 错误码

推荐错误码：

| 错误码 | 含义 |
| --- | --- |
| `INVALID_ARGUMENT` | 参数非法。 |
| `TARGET_NOT_FOUND` | 目标不存在。 |
| `TARGET_UNREACHABLE` | 目标不可连接。 |
| `POLICY_BLOCKED` | 策略阻断。 |
| `POLICY_REQUIRES_APPROVAL` | 需要创建和审批 Plan。 |
| `PLAN_NOT_FOUND` | Plan 不存在。 |
| `PLAN_HASH_MISMATCH` | Plan 内容哈希不匹配。 |
| `PLAN_EXPIRED` | Plan 已过期。 |
| `PLAN_NOT_APPROVED` | Plan 尚未审批。 |
| `PLAN_ALREADY_EXECUTED` | Plan 已执行。 |
| `RUN_FAILED` | 执行失败。 |
| `SSH_ACQUIRE_TIMEOUT` | 获取 SSH 连接超时。 |
| `SSH_COMMAND_TIMEOUT` | 远程命令执行超时。 |
| `SSH_CONNECTION_BROKEN` | SSH 连接断开。 |
| `AUDIT_WRITE_FAILED` | 审计写入失败。 |

### 17.3 输出截断

MCP 返回不应无上限返回远程输出。

建议：

- stdout/stderr 默认返回 excerpt。
- 完整输出通过 artifact 或后续查询机制获取。
- excerpt 必须脱敏。
- 返回中包含 `truncated: true` 表示输出被截断。

示例：

```json
{
  "stdout_excerpt": "...",
  "stdout_truncated": true,
  "stdout_digest": "sha256:abc123"
}
```

### 17.4 目标地址脱敏

MCP 返回中不得暴露真实远程地址。

禁止返回：

- 真实 IPv4 地址。
- 真实 IPv6 地址。
- 真实 hostname。
- SSH 端口。
- 跳板机真实地址和端口。

允许返回：

- `target_alias`。
- 脱敏后的 `host_display`。
- `has_jump_host`。
- 连接是否可达。
- 认证类型摘要，例如 `key` 或 `password`。

脱敏示例：

| 原始值 | 返回值 |
| --- | --- |
| `192.168.1.10` | `192.168.*.*` |
| `10.0.2.15` | `10.0.*.*` |
| `2001:db8:abcd::10` | `2001:db8:*` |
| `prod-db-01.internal.example.com` | `prod-db-01.*` |

端口不做脱敏返回，规则是完全不返回。

该规则适用于：

- MCP tool 返回。
- MCP resource 返回。
- Plan 摘要。
- Audit 查询结果。
- 错误消息。
- 健康检查结果。

## 18. MCP 审批语义

MCP 审批不是 MCP client 的提示词约定，而是服务端状态机。

审批必须绑定：

- `plan_id`
- `plan_hash`
- `approved_by`
- `approved_at`
- `expires_at`

审批不应只依赖自然语言确认。

错误示例：

```text
User said yes, so execute latest plan.
```

正确示例：

```text
User approved plan_id=plan_01 with plan_hash=sha256:abc123.
```

执行时必须验证：

- Plan 存在。
- Plan hash 匹配。
- Plan 状态为 `approved`。
- Plan 未过期。
- Plan 未执行过。

## 19. MCP 审计上下文

每次 MCP tool 调用都应构造审计上下文。

推荐模型：

```python
@dataclass(frozen=True)
class McpRequestContext:
    request_id: str
    client_name: str
    tool_name: str
    actor: str
    session_id: str | None = None
```

审计事件中应包含：

- `request_id`
- `client_name`
- `tool_name`
- `actor`
- `target_alias`
- `host_display`
- `plan_id`
- `run_id`

这样可以从审计反查：哪个 MCP client 通过哪个 tool 发起了哪个远程操作。

审计事件对外查询时不得返回真实 IP、hostname 或端口。内部如需定位目标，应使用 `target_alias`、`target_key` 或受控存储中的目标引用。

## 20. MCP 安全边界

### 20.1 不可信输入

MCP client 输入全部视为不可信。

不可信字段包括：

- `risk_level`
- `requires_approval`
- `approved_by`
- `workdir`
- `command`
- `remote_path`
- `local_path`
- `metadata`

其中 `risk_level` 和 `requires_approval` 不应接受 client 输入，只能由服务端生成。

### 20.2 禁止绕过路径

以下行为必须禁止：

- MCP tool 直接调用 `ssh.executor.exec_command` 执行未经过 policy 的指令。
- MCP tool 根据用户自然语言“同意”直接执行最近 Plan。
- MCP tool 使用 client 传入的 `risk_level` 决定是否审批。
- MCP tool 在审计失败时继续执行高风险操作。
- MCP tool 返回未脱敏的 secret。
- MCP tool 返回真实 IP、hostname 或 SSH 端口。

### 20.3 审计失败策略

建议策略：

| 操作类型 | 审计写入失败时行为 |
| --- | --- |
| 低风险只读 | 可执行，但必须返回审计失败警告。 |
| 中风险 | 默认拒绝执行。 |
| 高风险 | 必须拒绝执行。 |
| 审批操作 | 必须拒绝。 |
| 写文件、删除、重启服务 | 必须拒绝。 |

理由：高风险操作如果没有审计，会破坏系统最核心的安全承诺。

## 21. 第一阶段 MCP 最小实现

第一阶段只实现以下 tools：

```text
remote_get_capabilities
remote_run_instruction
remote_create_plan
remote_get_plan
remote_list_plans
remote_approve_plan
remote_reject_plan
remote_execute_plan
remote_list_audit_events
```

暂不实现：

- MCP resources。
- 流式日志。
- 交互式 shell。
- artifact 下载。
- 多人审批。
- 分布式队列。

第一阶段必须保证：

- 所有执行入口都经过 policy。
- 高风险 instruction 不能直接执行。
- Plan 审批绑定 plan hash。
- 执行前重新校验 Plan。
- 审计覆盖 Plan、Approval、Run、Step。
- 输出脱敏和截断。

## 22. MCP Resources 设计

MCP resources 适合只读查询，不适合作为执行入口。

可选 resources：

```text
remote://targets
remote://plans
remote://plans/{plan_id}
remote://runs/{run_id}
remote://audit
remote://audit/{run_id}
remote://capabilities
```

Resources 规则：

- 只能读取状态。
- 不能触发远程执行。
- 不能改变 Plan 状态。
- 不能审批。
- 不能返回 secret。

第一阶段可以不实现 resources，全部通过 tools 查询。等 MCP client 对 resources 支持更稳定后再补。
