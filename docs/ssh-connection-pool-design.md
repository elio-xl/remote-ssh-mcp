# SSH Connection Pool Design

## 目标

本设计用于 `remote-ssh-mcp` 的远程 SSH 操作层。连接池负责复用 SSH 连接、控制并发、隔离长任务，并为 Codex、Claude、Web UI 等 MCP 客户端提供稳定的远程执行基础。

连接池只负责连接生命周期和资源调度，不负责命令风险判断、审批、审计和 MCP tool 路由。

## 设计原则

- 同一个服务器允许多个 SSH 连接。
- 同一个 SSH 连接允许多个 channel。
- 普通短命令优先复用连接。
- 长任务、交互 shell、持续日志流应独占或降低共享优先级。
- SFTP 复用底层 SSH transport，但每次操作创建临时 SFTP client。
- 连接池必须有上限，不能无限扩容。
- 非核心空闲连接应自动关闭。
- 连接失效时允许自动重连一次。
- 连接池不持久化活连接，进程退出即释放。

## 非目标

连接池不处理以下职责：

- MCP `tools/list` 或 `tools/call` 协议。
- 命令 allowlist、blocklist、risk classification。
- plan、approval、audit 工作流。
- 凭证加密存储。
- 跨进程连接共享。
- 远程命令输出脱敏。

这些职责应由 `mcp`、`security`、`plans`、`audit`、`credentials` 等模块处理。

## 与数据库连接池的相似点

SSH 连接池可参考数据库连接池的核心概念：

- `core_connections_per_target`: 每个目标的核心连接数。
- `max_connections_per_target`: 每个目标的最大连接数。
- `idle_timeout_seconds`: 非核心连接空闲回收时间。
- `acquire_timeout_seconds`: 获取连接等待超时。
- `keepalive_seconds`: 保活间隔。
- `cleanup_interval_seconds`: 后台清理间隔。

## 与数据库连接池的差异

SSH 和数据库连接有关键差异：

- 一个 SSH transport 可以打开多个 channel。
- SSH 命令可能是长任务，例如 `tail -f`、部署脚本、文件传输。
- 交互 shell 应独占连接，不能和普通命令混用。
- SSH 网络中断和跳板机断开更常见。
- SFTP 是 SSH transport 上的子系统，应按操作临时创建。

因此 SSH 连接池需要同时控制：

- 每个 target 的 SSH connection 数量。
- 每个 SSH connection 的 channel 并发数量。
- 不同 purpose 的调度策略。

## 配置

推荐默认配置：

```yaml
ssh_pool:
  default:
    core_connections_per_target: 1
    max_connections_per_target: 3
    max_channels_per_connection: 4
    idle_timeout_seconds: 600
    keepalive_seconds: 30
    acquire_timeout_seconds: 10
    connect_timeout_seconds: 8
    command_timeout_seconds: 60
    cleanup_interval_seconds: 60
    warmup_on_start: false

  targets:
    prod-*:
      core_connections_per_target: 1
      max_connections_per_target: 2
      max_channels_per_connection: 2
      idle_timeout_seconds: 300

    dev-*:
      core_connections_per_target: 1
      max_connections_per_target: 5
      max_channels_per_connection: 6
      idle_timeout_seconds: 900
```

配置含义：

| 配置项 | 含义 |
| --- | --- |
| `core_connections_per_target` | 每个目标保持的核心连接数。 |
| `max_connections_per_target` | 每个目标允许的最大 SSH transport 数。 |
| `max_channels_per_connection` | 单个 SSH transport 允许的最大并发 channel 数。 |
| `idle_timeout_seconds` | 非核心连接空闲多久后关闭。 |
| `keepalive_seconds` | SSH transport keepalive 间隔。 |
| `acquire_timeout_seconds` | 等待可用连接的最长时间。 |
| `connect_timeout_seconds` | 新建 SSH 连接超时。 |
| `command_timeout_seconds` | 默认命令执行超时。 |
| `cleanup_interval_seconds` | 后台清理空闲连接的周期。 |
| `warmup_on_start` | 启动时是否预热核心连接。默认关闭。 |

## Target Key

连接池不能只按 `hostname` 分组。不同用户、认证方式、私钥、跳板机会话不能混用。

推荐 target key：

```text
sha256(alias, hostname, port, username, auth_identity, jump_host_identity)
```

`auth_identity` 可由以下字段组合：

```text
auth_type
identity_file
private_key_fingerprint
password_session_marker
```

如果使用密码建立一次性会话，不应和保存的 key-based credential 复用同一个 key。

## 数据模型

建议模型：

```python
@dataclass(frozen=True)
class ConnectionTarget:
    alias: str
    hostname: str
    port: int
    username: str
    auth_type: str
    identity_file: str | None = None
    private_key_passphrase: str | None = None
    jump_host: "ConnectionTarget | None" = None


@dataclass
class SSHPoolConfig:
    core_connections_per_target: int = 1
    max_connections_per_target: int = 3
    max_channels_per_connection: int = 4
    idle_timeout_seconds: int = 600
    keepalive_seconds: int = 30
    acquire_timeout_seconds: int = 10
    connect_timeout_seconds: int = 8
    command_timeout_seconds: int = 60
    cleanup_interval_seconds: int = 60
    warmup_on_start: bool = False


@dataclass
class PooledSSHConnection:
    id: str
    target_key: str
    target: ConnectionTarget
    client: paramiko.SSHClient
    created_at: float
    last_used_at: float
    in_flight: int
    is_core: bool
    is_dedicated: bool
```

连接用途：

```python
ConnectionPurpose = Literal[
    "exec",
    "sftp",
    "long_running",
    "interactive",
]
```

## 模块划分

结合 `CLAUDE.md` 的约束，避免把所有 SSH 逻辑塞进一个大文件。

推荐结构：

```text
backend/
  ssh/
    models.py          # ConnectionTarget, SSHPoolConfig, PooledSSHConnection
    pool.py            # SSHConnectionPool
    factory.py         # 创建 paramiko client，处理 jump host
    executor.py        # exec_command、read_file
    sftp.py            # upload、download、hash

  utils/
    ssh.py             # expand_path、key loading 等通用 SSH 工具
```

如果当前项目暂时不拆 `backend/ssh/` 包，也可以先放：

```text
backend/ssh_pool.py
backend/ssh_executor.py
```

但不要修改 `backend/connection_test.py` 的职责。它应继续只做一次性连接测试。

## 连接获取流程

`acquire()` 流程：

```text
1. 根据 ConnectionTarget 计算 target_key。
2. 获取该 target 的 bucket。
3. 清理 bucket 中已断开的连接。
4. 找出健康且可用的连接。
5. 对普通 exec/sftp，选择 in_flight 最少的连接。
6. 如果没有可用连接，且未达到 max_connections_per_target，则新建连接。
7. 如果达到最大连接数，则等待 acquire_timeout_seconds。
8. 超时后返回 PoolBusyError。
```

伪代码：

```python
def acquire(
    target: ConnectionTarget,
    purpose: ConnectionPurpose = "exec",
    timeout: float | None = None,
) -> PooledSSHConnection:
    bucket = buckets[target_key(target)]
    remove_dead_connections(bucket)

    if purpose == "interactive":
        return acquire_dedicated_connection(bucket, target)

    available = [
        conn
        for conn in bucket.connections
        if conn.is_active()
        and not conn.is_dedicated
        and conn.in_flight < config.max_channels_per_connection
    ]

    if available:
        conn = min(available, key=lambda item: item.in_flight)
        conn.in_flight += 1
        conn.last_used_at = time.monotonic()
        return conn

    if bucket.live_count < config.max_connections_per_target:
        conn = open_new_connection(target)
        conn.in_flight = 1
        bucket.connections.append(conn)
        return conn

    return wait_for_available_connection(bucket, timeout)
```

## 连接释放流程

`release()` 流程：

```text
1. 将 in_flight 减 1。
2. 更新 last_used_at。
3. 如果连接已失效，关闭并移出 bucket。
4. 通知等待 acquire 的线程或 coroutine。
```

必须保证 `release()` 在 `finally` 中执行。

示例：

```python
conn = pool.acquire(target, purpose="exec")
try:
    return executor.exec(conn, command)
finally:
    pool.release(conn)
```

## Purpose 调度规则

| Purpose | 调度策略 |
| --- | --- |
| `exec` | 共享连接，按最少 `in_flight` 选择。 |
| `sftp` | 共享 SSH transport，每次创建临时 SFTP client。 |
| `long_running` | 优先选择空闲连接；必要时新建连接；降低被后续短命令选中的优先级。 |
| `interactive` | 独占连接，不参与普通 exec/sftp 调度。 |

长任务判断可来自调用方：

- 用户显式声明 `long_running=true`。
- policy 判断命令含 `tail -f`、`watch`、`top` 等持续运行模式。
- 命令超时时间显著高于默认值。

## 核心连接与非核心连接

核心连接行为：

- target 第一次使用时懒加载创建。
- 默认不因空闲而关闭。
- 健康检查失败时关闭，后续按需重建。

非核心连接行为：

- 只有在并发压力下创建。
- 空闲超过 `idle_timeout_seconds` 后关闭。
- 优先被清理。

默认不建议启动时预热全部核心连接，因为 MCP server 启动时不应阻塞在远程网络和认证上。

## 健康检查

基础健康检查：

```python
transport = client.get_transport()
active = transport is not None and transport.is_active()
```

深度健康检查可选：

```text
执行轻量命令 `true` 或 `echo ok`
```

深度检查不应频繁执行，避免影响远程主机。

建议：

- `acquire()` 时做基础检查。
- 命令失败且怀疑 transport 失效时做一次重连。
- `health` tool 可按需做深度检查。

## Keepalive

新建连接后设置 keepalive：

```python
transport = client.get_transport()
if transport is not None:
    transport.set_keepalive(config.keepalive_seconds)
```

keepalive 用于降低 NAT、跳板机或防火墙清理空闲连接的概率，但不能替代健康检查。

## 错误处理

推荐错误类型：

```python
class SSHConnectionError(RuntimeError): ...
class PoolBusyError(RuntimeError): ...
class SSHAcquireTimeoutError(RuntimeError): ...
class SSHCommandTimeoutError(RuntimeError): ...
class SSHConnectionBrokenError(RuntimeError): ...
```

处理策略：

- 新建连接失败：返回明确连接错误。
- acquire 超时：返回 busy，不自动扩大上限。
- 命令执行中 transport 断开：关闭该连接，允许重连后重试一次。
- 命令已经产生副作用时不能自动重试。
- 文件上传、写入、系统变更必须由 plan/executor 决定是否可重试。

## 并发模型

`CLAUDE.md` 指定项目使用 `asyncio`，但 `paramiko` 是阻塞 IO。

推荐第一版：

```text
async MCP tool handler
  -> asyncio.to_thread(blocking SSH operation)
  -> thread-safe SSHConnectionPool
```

连接池内部使用标准库锁：

```python
threading.RLock
threading.Condition
```

不要在第一版引入额外第三方异步 SSH 库。

## 命令执行与 Channel

每条命令应打开独立 channel。

建议执行流程：

```text
1. acquire pooled connection。
2. 通过 SSHClient.exec_command 或 Transport.open_session 打开 channel。
3. 设置 timeout。
4. 读取 stdout/stderr。
5. 获取 exit status。
6. close channel。
7. release pooled connection。
```

不要长期复用同一个 channel。

## SFTP

SFTP 建议按操作创建：

```python
conn = pool.acquire(target, purpose="sftp")
try:
    sftp = conn.client.open_sftp()
    try:
        return upload_or_download(sftp)
    finally:
        sftp.close()
finally:
    pool.release(conn)
```

不要把 SFTP client 放进池里长期复用。

## 审计集成点

连接池本身不写完整审计，但可以向上层返回事件信息。

建议由 operation service 写审计：

- `connection_opened`
- `connection_reused`
- `connection_closed`
- `connection_failed`
- `pool_busy`

审计日志不要记录密码、passphrase、私钥内容。

## MCP Tool 建议

可暴露以下连接池相关 tool：

```text
ssh_list_connections
ssh_connection_health
ssh_close_connection
ssh_pool_stats
```

示例返回：

```json
{
  "targets": [
    {
      "alias": "dev-box",
      "live_connections": 2,
      "core_connections": 1,
      "in_flight": 3,
      "max_connections": 3,
      "max_channels_per_connection": 4,
      "idle_timeout_seconds": 600
    }
  ]
}
```

## 安全注意事项

- 连接池不应在日志中输出密码、passphrase 或私钥路径之外的敏感材料。
- 如果 password-based 连接是一次性会话，不应保存可复用 credential。
- 不同用户、不同私钥、不同 jump host 不能混用同一个连接。
- `interactive` 连接必须独占，避免用户输入泄漏到其他操作。
- 生产目标建议降低 `max_connections_per_target` 和 `max_channels_per_connection`。

## 推荐默认值

第一版默认值：

```yaml
ssh_pool:
  core_connections_per_target: 1
  max_connections_per_target: 3
  max_channels_per_connection: 4
  idle_timeout_seconds: 600
  keepalive_seconds: 30
  acquire_timeout_seconds: 10
  connect_timeout_seconds: 8
  command_timeout_seconds: 60
  cleanup_interval_seconds: 60
  warmup_on_start: false
```

生产目标覆盖：

```yaml
ssh_pool:
  targets:
    prod-*:
      core_connections_per_target: 1
      max_connections_per_target: 2
      max_channels_per_connection: 2
      idle_timeout_seconds: 300
```

## 实现顺序

建议按以下顺序落地：

1. 定义 `ConnectionTarget`、`SSHPoolConfig`、`PooledSSHConnection`。
2. 实现 target key 生成和配置解析。
3. 实现 `SSHConnectionPool.acquire()`、`release()`、`close_idle()`。
4. 实现 `SSHConnectionFactory`，负责创建 Paramiko client 和 jump host。
5. 实现 `SSHExecutor.exec_command()`，每条命令使用独立 channel。
6. 实现 SFTP 操作，每次使用临时 SFTP client。
7. 增加 `ssh_pool_stats` 和 `ssh_connection_health` MCP tools。
8. 将 plan、approval、audit 接入 operation service，而不是接入 pool。

## 最终结论

连接池应采用数据库连接池风格的配置，但不能完全照搬数据库模型。

最终策略：

```text
每个 target 有核心 SSH 连接
并发压力下扩容到最大连接数
每个 SSH 连接允许有限 channel 并发
长任务和交互任务隔离
非核心连接空闲回收
连接失效时清理并按需重连
```

这能支撑 Codex、Claude 和 Web UI 多端并发，同时避免远程服务器被无限连接或长任务阻塞。
