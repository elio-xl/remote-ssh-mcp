# MCP 文件上传 Transfer Job 改造方案

## 背景

当前 `sftp_put` 上传逻辑在 `backend/remote/runner.py` 中同步执行。Claude 调用 `remote_execute_plan` 后，会一直等待 MCP tool call 返回。大文件上传期间，Claude 无法继续输出“正在上传哪个文件”、无法展示实时进度，也无法响应用户的取消请求。

当前关键路径：

```text
Claude
  -> remote_create_plan
  -> remote_approve_plan
  -> remote_execute_plan
    -> RemoteApplicationService.execute_plan()
      -> RemoteRunner.run_plan()
        -> RemoteRunner._run_sftp_put()
          -> upload_file(..., callback=transfer_callback)
          -> verify hash
          -> rename / backup / cleanup
  <- 上传完成后一次性返回结果
```

当前 `runner.py` 中的 `transfer_callback(transferred, total)` 只更新局部变量 `bytes_transferred` 并检查超时。它没有把进度写入可查询状态，也没有通过 MCP 返回中间消息。因此 Claude 只能看到一个长时间运行的工具调用。

## 目标

把文件上传从“同步阻塞的 plan step”改成“提交任务 + 后台执行 + 进度轮询 + 可取消”的模型。

目标能力：

- Claude 提交上传任务后立即拿到 `transfer_id`。
- Claude 能向用户明确说明正在上传的 `local_path -> remote_path`。
- Claude 能定时调用 `remote_get_transfer` 查询进度。
- 用户要求停止时，Claude 能调用 `remote_cancel_transfer`。
- 后台上传仍复用现有安全校验、审批、冲突处理、原子写入、hash 校验逻辑。
- 上传任务状态可供桌面 App 和审计系统查询。

非目标：

- 第一阶段不做断点续传。
- 第一阶段不做多文件批量上传队列。
- 第一阶段不允许绕过 plan / approval。
- 第一阶段不要求服务进程重启后恢复正在上传的任务。

## 推荐交互流程

### Claude 流程

```text
1. remote_list_targets
2. remote_create_plan
3. 用户确认后 remote_approve_plan
4. remote_start_transfer
5. Claude 立即告知用户：
   - transfer_id
   - local_path_display
   - remote_path
   - target_alias
   - bytes_total
   - conflict_policy
6. 每 30s 或 60s 调 remote_get_transfer
7. 如果用户要求取消，调 remote_cancel_transfer
8. 完成后汇总：
   - status
   - bytes_total
   - elapsed_seconds
   - remote_sha256
   - actual_remote_path
   - backup_remote_path
```

### MCP 工具流程

```text
remote_create_plan
  -> 创建高风险上传计划

remote_approve_plan
  -> 审批计划

remote_start_transfer
  -> 校验 plan 已审批
  -> 校验 step 是 sftp_put
  -> 从已审批 plan step 读取 instruction，禁止客户端覆盖路径或执行参数
  -> 创建 TransferRecord
  -> 启动后台 worker
  -> 立即返回 transfer_id

remote_get_transfer
  -> 返回任务状态、进度、速度、ETA、错误信息

remote_cancel_transfer
  -> 标记 cancel_requested
  -> worker 在 callback 中检测并中断
```

## 新增 MCP Tools

### remote_start_transfer

用途：启动已审批 plan 中的上传 step，返回 `transfer_id`，不阻塞等待上传完成。

请求：

```json
{
  "plan_id": "plan-xxx",
  "plan_hash": "sha256:...",
  "step_id": "step-xxx"
}
```

响应：

```json
{
  "success": true,
  "transfer_id": "transfer-xxx",
  "status": "pending",
  "target_alias": "prod",
  "local_path_display": "./deploy.tar.gz",
  "remote_path": "/opt/app/deploy.tar.gz",
  "bytes_total": 104857600,
  "poll_after_seconds": 30
}
```

说明：

- `status` 必须返回创建后的实际状态，通常是 `pending` 或 `running`。后台线程可能尚未开始执行，不应固定返回 `running`。
- MCP 响应默认返回 `local_path_display`，优先使用 workspace-relative path 或脱敏后的路径；完整绝对路径只应在本地 App 或受控配置下返回。

规则：

- plan 必须存在。
- plan hash 必须匹配。
- plan 必须处于 `approved` 状态。
- step 必须存在且 `instruction.kind == "sftp_put"`。
- `remote_start_transfer` 只接受 `plan_id`、`plan_hash`、`step_id`，不接受 `local_path`、`remote_path`、`mode`、`verify`、`conflict_policy` 等执行参数。
- worker 必须从 plan store 中重新读取已审批 step 的 instruction，确保实际执行内容与用户审批内容一致。
- 同一个 step 默认只能启动一个 active transfer。
- 高风险上传不能通过该工具绕过审批。
- 启动成功后，plan 建议进入 `executing` 状态；transfer 终态为 `succeeded` 时再进入 `executed`，终态为 `failed` / `timed_out` / `cancelled` 时进入 `failed` 或 `partially_executed`。
- 如果第一阶段暂不扩展 plan status，必须至少在 plan metadata 中写入 `active_transfer_id` / `last_transfer_status`，并禁止重复启动同一 step 的 active transfer。

### remote_get_transfer

用途：查询单个上传任务状态。

请求：

```json
{
  "transfer_id": "transfer-xxx"
}
```

响应：

```json
{
  "success": true,
  "transfer": {
    "transfer_id": "transfer-xxx",
    "direction": "upload",
    "status": "running",
    "target_alias": "prod",
    "plan_id": "plan-xxx",
    "run_id": "run-xxx",
    "step_id": "step-xxx",
    "local_path_display": "./deploy.tar.gz",
    "remote_path": "/opt/app/deploy.tar.gz",
    "actual_remote_path": "/opt/app/deploy.tar.gz",
    "temp_remote_path": "/opt/app/deploy.tar.gz.tmp.transfer-xxx",
    "bytes_total": 104857600,
    "bytes_transferred": 52428800,
    "percent": 50.0,
    "bytes_per_second": 2097152,
    "eta_seconds": 25,
    "started_at": 1781090000.0,
    "updated_at": 1781090025.0,
    "error_type": null,
    "error_message": null
  }
}
```

### remote_cancel_transfer

用途：请求取消上传任务。

请求：

```json
{
  "transfer_id": "transfer-xxx",
  "reason": "user requested cancellation"
}
```

响应：

```json
{
  "success": true,
  "transfer_id": "transfer-xxx",
  "status": "cancel_requested",
  "message": "cancel requested"
}
```

规则：

- 第一阶段只允许对 `pending` / `running` 状态设置 `cancel_requested = true`。
- 对 `verifying` / `renaming` 状态默认返回 `cannot_cancel`，避免 hash 校验、备份、rename 阶段产生不确定远端状态。
- 对终态任务返回当前状态，不重复取消。
- worker 在 SFTP callback 中检测取消标记并抛出 `TransferCancelled`。
- 取消后尽力删除临时文件，并记录 cleanup 结果。

### remote_list_transfers

用途：供 Claude 或桌面 App 查询最近上传记录。

请求：

```json
{
  "target_alias": "prod",
  "status": "running",
  "limit": 20
}
```

响应：

```json
{
  "success": true,
  "transfers": []
}
```

## 新增模块

建议新增这些文件，而不是把所有逻辑继续堆进 `runner.py`：

```text
backend/remote/transfer_models.py
backend/remote/transfer_store.py
backend/remote/transfer_worker.py
backend/remote/transfer_service.py
```

### transfer_models.py

定义 transfer 数据结构。

建议字段：

```python
TransferStatus = Literal[
    "pending",
    "running",
    "verifying",
    "renaming",
    "succeeded",
    "failed",
    "cancel_requested",
    "cancelled",
    "timed_out",
    "conflict",
]

@dataclass
class TransferRecord:
    transfer_id: str
    direction: Literal["upload", "download"]
    status: TransferStatus
    target_alias: str
    plan_id: str | None
    run_id: str | None
    step_id: str | None
    actor: str
    local_path: str
    local_path_display: str
    remote_path: str
    actual_remote_path: str
    temp_remote_path: str
    backup_remote_path: str
    conflict_policy: str
    atomic: bool
    verify: bool
    bytes_total: int
    bytes_transferred: int
    percent: float
    bytes_per_second: float | None
    eta_seconds: float | None
    local_sha256: str | None
    remote_sha256: str | None
    cancel_requested: bool
    started_at: float | None
    transfer_started_at: float | None
    transfer_finished_at: float | None
    finished_at: float | None
    elapsed_seconds: float | None
    error_type: str | None
    error_message: str | None
    cleanup_failed: bool
    created_at: float
    updated_at: float
```

说明：

- `local_path` 是服务端内部使用的规范化路径，默认不直接暴露给 MCP 客户端。
- `local_path_display` 是对 Claude / App 展示的路径，优先使用 workspace-relative path 或脱敏后的路径。
- 如果 `remote_start_transfer` 不经过 `RemoteRunner.run_plan()`，第一阶段可以不生成 `run_id`，保持 `run_id = None`，只关联 `plan_id` / `step_id` / `transfer_id`。
- 如果需要完整沿用现有 run 审计模型，`TransferService.start_transfer()` 应显式创建一个 run record，并把 `run_id` 写入 transfer metadata。

### transfer_store.py

职责：保存和更新 transfer 状态。

第一阶段建议：

- 内存字典保存运行中任务。
- JSON 文件或 JSONL 文件持久化历史任务。
- 使用 `threading.Lock` 保证并发更新安全。
- 高频进度只更新内存。
- 每 2 秒或每 16MB 持久化一次。
- 终态必须立即持久化。

存储格式建议：

- 第一阶段优先使用单个 `transfers.json`，通过临时文件 + 原子 rename 写入，避免同一 `transfer_id` 多条记录合并问题。
- 如果使用 JSONL append-only，`get()` / `list()` 必须按 `transfer_id` 聚合并返回最后一条状态，不能把同一任务的历史快照当作多个任务。
- 运行中任务必须以内存状态为准，持久化状态只作为查询和历史恢复的辅助。

核心接口：

```python
class TransferStore:
    def create_upload(...): ...
    def get(transfer_id: str) -> TransferRecord | None: ...
    def list(...): ...
    def update_progress(transfer_id: str, transferred: int, total: int): ...
    def mark_status(transfer_id: str, status: TransferStatus): ...
    def mark_succeeded(...): ...
    def mark_failed(...): ...
    def request_cancel(transfer_id: str, reason: str | None): ...
    def is_cancel_requested(transfer_id: str) -> bool: ...
```

### transfer_worker.py

职责：后台执行上传。

并发控制：

- 第一阶段必须设置保守默认值：全局最多 2 个 running transfer，每个 target 最多 1 个 running transfer。
- 超过限制时，推荐让任务保持 `pending` 并由 worker queue 调度；如果暂不实现队列，则 `remote_start_transfer` 应返回 `too_many_transfers`，不要无上限创建线程。
- 后台线程建议由 `ThreadPoolExecutor(max_workers=N)` 管理，而不是每个请求直接创建裸线程。

核心逻辑从 `RemoteRunner._run_sftp_put()` 中拆出，但要把局部变量状态更新到 `TransferStore`。

伪代码：

```python
def run_upload_job(job: UploadJob) -> None:
    record = store.get(job.transfer_id)
    store.mark_status(job.transfer_id, "running")

    conn = None
    try:
        conn = pool.acquire(target, purpose="sftp", timeout=instruction.timeout_seconds)
        validate local_path / remote_path
        compute local_sha256
        handle conflict
        choose temp_remote_path

        def callback(transferred: int, total: int) -> None:
            if store.is_cancel_requested(job.transfer_id):
                raise TransferCancelled("upload cancelled by user")
            check_timeout(deadline, "upload")
            store.update_progress(job.transfer_id, transferred, total)

        upload_file(conn, local_path, temp_remote_path, callback=callback)

        store.mark_status(job.transfer_id, "verifying")
        verify remote sha256

        store.mark_status(job.transfer_id, "renaming")
        rename temp path to final path

        store.mark_succeeded(job.transfer_id, metadata)
    except TransferCancelled:
        delete temp file best-effort
        store.mark_cancelled(job.transfer_id, cleanup_failed=cleanup_failed)
    except TimeoutError as exc:
        delete temp file best-effort
        store.mark_timed_out(job.transfer_id, error_type="TimeoutError", error_message=str(exc))
    except Exception as exc:
        rollback backup best-effort
        delete temp file best-effort
        store.mark_failed(job.transfer_id, type(exc).__name__, str(exc))
    finally:
        if conn is not None:
            pool.release(conn)
```

### transfer_service.py

职责：连接 plan、审批、runner、worker。

核心接口：

```python
class TransferService:
    def start_transfer(plan_id: str, plan_hash: str | None, step_id: str, actor: str) -> dict: ...
    def get_transfer(transfer_id: str) -> dict: ...
    def cancel_transfer(transfer_id: str, reason: str | None, actor: str) -> dict: ...
    def list_transfers(...) -> dict: ...
```

## runner.py 的调整

`runner.py` 不建议继续承担后台任务管理职责。它当前适合执行同步 instruction，但上传变成 transfer job 后，应做角色收缩。

推荐调整：

- 保留普通 shell / read_file 的同步执行。
- 将 `_run_sftp_put()` 中可复用的校验和上传步骤迁移到 `transfer_worker.py`。
- `RemoteRunner.run_plan()` 遇到 `sftp_put` 时有两种模式：
  - 同步兼容模式：继续等待上传完成，主要用于测试或旧客户端。
  - 异步模式：创建 transfer job，返回包含 `transfer_id` 的 `StepResult`。
- MCP 面向 Claude 默认使用异步模式。

不推荐：

- 在 `runner.py` 的 SFTP callback 中高频写 `AuditStore`。
- 在 `remote_execute_plan` 同步调用中等待大文件上传完成。
- 只通过 `remote_list_audit_events` 模拟实时进度。

## service.py 的调整

`RemoteApplicationService` 增加 transfer 相关方法：

```python
def start_transfer(self, *, plan_id: str, plan_hash: str | None, step_id: str, actor: str) -> dict[str, object]: ...
def get_transfer(self, *, transfer_id: str) -> dict[str, object]: ...
def cancel_transfer(self, *, transfer_id: str, reason: str | None, actor: str) -> dict[str, object]: ...
def list_transfers(self, *, target_alias: str | None, status: str | None, limit: int) -> dict[str, object]: ...
```

初始化时注入：

```python
self.transfer_store = transfer_store or TransferStore()
self.transfer_service = TransferService(
    plan_store=self.plan_store,
    audit_store=self.audit_store,
    transfer_store=self.transfer_store,
    pool=self.pool,
    target_resolver=self._resolve_target,
)
```

plan 状态建议：

- 长期建议把 `PlanStatus` 扩展为 `executing`、`failed`、`partially_executed`，否则异步 transfer 无法准确表达执行中和执行失败。
- 第一阶段如果不扩展模型，`remote_start_transfer` 必须在 plan metadata 中记录 `active_transfer_id`，并在 transfer 终态后写入 `last_transfer_status`。
- 同一个 plan step 存在 active transfer 时，重复调用 `remote_start_transfer` 应返回已有 `transfer_id` 或明确返回 `transfer_already_running`。

## ssh_mcp_server.py 的调整

`_tools()` 新增：

```text
remote_start_transfer
remote_get_transfer
remote_cancel_transfer
remote_list_transfers
```

`_dispatch_tool()` 新增对应分支。

工具描述要明确告诉 Claude：

- `remote_start_transfer` 会立即返回，不等待上传完成。
- 上传状态必须通过 `remote_get_transfer` 查询。
- 用户要求停止时调用 `remote_cancel_transfer`。

## Skill 调整

`skills/remote-ssh/SKILL.md` 必须明确上传行为，否则 Claude 可能仍旧调用旧的同步流程。

建议新增规则：

```text
上传文件时必须使用异步 transfer 流程：
1. 创建并审批 plan。
2. 调用 remote_start_transfer 启动上传。
3. 启动后立即向用户说明：transfer_id、local_path_display、remote_path、target_alias、bytes_total。
4. 上传未完成时，每 60 秒调用 remote_get_transfer 并报告 percent、速度、ETA。
5. 用户要求停止上传时，调用 remote_cancel_transfer，不要尝试用 Bash 终止进程。
6. 完成后报告 actual_remote_path、remote_sha256、elapsed_seconds、backup_remote_path。
```

## 状态机

```text
pending
  -> running
  -> verifying
  -> renaming
  -> succeeded

pending/running
  -> cancel_requested
  -> cancelled

pending/running/verifying/renaming
  -> failed

running
  -> timed_out

pending
  -> conflict
```

说明：

- `cancel_requested` 是用户已请求取消，但 worker 还没完成清理的中间状态。
- `cancelled` 是 worker 已停止并完成清理后的终态。
- `conflict` 用于需要用户决策的目标文件冲突。第一阶段也可以继续沿用 `conflict_policy == fail` 直接失败。
- 第一阶段不支持取消 `verifying` / `renaming`，这两个阶段的取消请求应返回 `cannot_cancel` 或 `too_late_to_cancel`。
- 超时终态使用 `status = "timed_out"`，不要同时写成 `status = "failed"`；`error_type` 可使用 `TimeoutError`。

## 进度计算

callback 输入：

```python
callback(transferred: int, total: int)
```

计算：

```text
percent = transferred / total * 100
bytes_per_second = 最近窗口增量字节 / 最近窗口秒数
eta_seconds = (total - transferred) / bytes_per_second
```

节流策略：

- 内存状态最多每 500ms 更新一次。
- 持久化最多每 2s 或每 16MB 更新一次。
- 状态变化、完成、失败、取消必须立即持久化。

## 取消机制

Paramiko `sftp.put()` 没有独立的取消 API。可行做法是在 callback 中检测取消标记并抛异常。

```python
class TransferCancelled(Exception):
    pass


def callback(transferred: int, total: int) -> None:
    if transfer_store.is_cancel_requested(transfer_id):
        raise TransferCancelled("upload cancelled")
    transfer_store.update_progress(transfer_id, transferred, total)
```

取消后的处理：

- 关闭 SFTP client。
- release 连接池连接。
- 尝试删除 `temp_remote_path`。
- 如果已备份原文件，按当前阶段决定是否恢复。
- 写入 `cancelled` 状态。
- 记录 `bytes_transferred`、`cleanup_failed`、`error_message`。

## 审计策略

Audit 不应承载高频进度。Audit 只记录关键事实：

- transfer_created
- transfer_started
- transfer_cancel_requested
- transfer_cancelled
- transfer_failed
- transfer_succeeded

如果不扩展 `AuditEventType`，可以先复用现有事件类型，并在 metadata 中写入 `transfer_id`。长期建议扩展专用事件类型。

避免：

- 每个 callback 都写 audit。
- 让 `remote_list_audit_events` 成为实时进度接口。

## 兼容策略

第一阶段可以同时保留旧同步上传路径，降低风险：

- `remote_execute_plan`：保持现状，用于旧客户端或小文件上传。
- `remote_start_transfer`：新异步路径，供 Claude 和 App 默认使用。

第二阶段再考虑让 `remote_execute_plan` 遇到 `sftp_put` 时默认返回 `transfer_id`，不再同步等待。

## 实施顺序

1. 新增 `TransferRecord` 和 `TransferStore`。
2. 新增 `remote_get_transfer` / `remote_list_transfers`，先返回静态记录，验证查询协议。
3. 从 `runner.py` 拆出上传执行逻辑到 `transfer_worker.py`。
4. 新增 `remote_start_transfer`，启动后台线程并返回 `transfer_id`。
5. 在 callback 中更新进度和检测取消。
6. 新增 `remote_cancel_transfer`。
7. 修改 skill，要求 Claude 上传时使用异步 transfer 流程并固定轮询。
8. 增加测试：成功上传、冲突、hash mismatch、超时、取消、进度更新节流。
9. 桌面 App 接入 `remote_get_transfer` / `remote_list_transfers`。

## 测试建议

单元测试：

- `TransferStore.create_upload()` 创建字段完整。
- `update_progress()` 正确计算 percent / speed / ETA。
- `request_cancel()` 正确设置 cancel flag。
- 终态任务不可重复取消。

集成测试：

- 小文件上传成功。
- 大文件上传期间可以查询 running 进度。
- 上传期间取消，状态变为 cancelled，临时文件被清理。
- 超时后状态变为 timed_out。
- hash mismatch 后状态变为 failed。
- `conflict_policy=fail` 时不会覆盖远端文件。
- `backup_then_overwrite` 成功时记录 backup path。

Claude 行为测试：

- 启动上传后立即输出 `transfer_id` 和路径。
- 上传未完成时按固定时间轮询。
- 用户说“停止上传”时调用 `remote_cancel_transfer`。
- 完成后输出最终路径、hash、耗时。

## 风险点

- 后台线程生命周期需要跟 MCP server 进程绑定，进程退出会中断上传。
- 多个上传任务并发时，需要限制全局并发和单 target 并发。
- `TransferStore` 高频持久化可能影响性能，必须节流。
- 取消不是硬中断，只能在 callback 被调用时生效。
- 如果上传卡在网络层且 callback 不再触发，只能依赖 socket timeout。
- plan 状态和 transfer 状态需要避免不一致，例如 plan 已 executed 但 transfer failed。

## 推荐最终架构

```text
Claude / Desktop App
  -> MCP tools
    -> RemoteApplicationService
      -> TransferService
        -> TransferStore
        -> TransferWorker thread
          -> SSHConnectionPool
          -> backend.ssh.sftp.upload_file()
          -> upload_utils validation / atomic rename / cleanup
      -> AuditStore
```

核心原则：

- MCP tool call 只传控制信息，不承载大文件内容。
- 大文件传输必须后台化。
- 实时进度属于 TransferStore，不属于 AuditStore。
- 高风险上传仍必须走 plan / approval。
- Claude 通过轮询 transfer 状态与用户保持交互。
