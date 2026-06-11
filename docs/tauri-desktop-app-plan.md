# Tauri/Rust 本地 App 开发方案

## 目标

构建一个 Remote SSH MCP 本地桌面 App，让用户可以直接管理 SSH 配置文件、安装 MCP 配置，并最终打包成可安装的 macOS 应用。

这份方案不走“先保留 HTTP 后端、再逐步迁移”的路线，而是直接进入本地 App 架构：

- 复用现有 `web` 里的 React/Vite 页面作为桌面 UI。
- Rust/Tauri 负责本地文件访问、MCP 配置安装、原生文件选择器、打包等本地能力。
- 第一版继续保留现有 Python MCP server，负责 agent 侧 MCP 调用和远程操作逻辑。
- 桌面 App 的 SSH config CRUD 不依赖 HTTP 后端。

开发需等本文档确认后再开始。

## 当前项目背景

当前相关文件：

- `web/`：现有 React/Vite UI。
- `backend/main.py`：当前 Web 模式使用的 HTTP API 服务。
- `backend/ssh_config_service.py`：Python 版 SSH config CRUD 实现。
- `ssh_mcp_server.py`：agent 使用的 stdio MCP server。
- `ssh_config`：当前仓库根目录下的本地 SSH 配置文件。
- `data/plans.json`：本地计划数据。
- `data/audit.jsonl`：本地审计日志。

重要约束：

当前 `ssh_config` 包含本机相关信息，包括真实服务器地址和私钥路径。它不能作为正式 App 的默认数据打包分发，只能作为开发期输入或导入来源。

## 目标架构

```text
Remote SSH MCP Desktop App
  |
  | React/Vite UI
  | - 复用现有 web 页面和组件
  | - 把 HTTP fetch 调用替换成 Tauri invoke 调用
  |
  v
Tauri Rust 层
  | - SSH config CRUD
  | - App 数据目录管理
  | - 私钥文件选择器
  | - MCP 客户端检测
  | - MCP 配置安装/卸载
  | - 打包集成
  |
  v
本地文件
  | - ~/Library/Application Support/Remote SSH MCP/ssh_config
  | - ~/Library/Application Support/Remote SSH MCP/data/plans.json
  | - ~/Library/Application Support/Remote SSH MCP/data/audit.jsonl

MCP 客户端
  |
  | stdio
  v
Python MCP Server，第一版保留
  | - ssh_mcp_server.py
  | - 通过环境变量读取 App 管理的数据路径
```

## 核心决策

### 1. 使用 Tauri，而不是纯 Swift App

优先选择 Tauri 的原因：

- 可以复用现有 React/Vite UI。
- Rust 能安全处理本地文件、配置合并、进程检测和原生对话框。
- 同一套架构后续可以扩展到 Windows/Linux。
- 可以打包成 macOS 原生应用，不需要像 Electron 那样额外打包完整浏览器运行时。

Swift 或 SwiftUI 仍然可行，但更适合只做 macOS 且愿意重写原生 UI 的情况。

### 2. 第一版保留 Python MCP Server

第一版不重写 MCP server。

原因：

- 现有 Python MCP 代码已经实现 agent 侧 MCP 协议。
- 现有 Python 逻辑已经覆盖 plan、audit、remote operation 等流程。
- 现在用 Rust 重写 SSH 行为会明显扩大范围和风险。
- 桌面 App 的核心价值可以先通过本地文件管理和 MCP 安装交付。

长期方向：

- 等桌面 UX 和 MCP 安装流程稳定后，再考虑把 Python MCP server 替换成 Rust 二进制。

### 3. 正式 App 数据必须移出仓库根目录

生产环境下，桌面 App 数据应放在用户应用数据目录。

macOS 目标路径：

```text
~/Library/Application Support/Remote SSH MCP/ssh_config
~/Library/Application Support/Remote SSH MCP/data/plans.json
~/Library/Application Support/Remote SSH MCP/data/audit.jsonl
```

仓库根目录的 `ssh_config` 不应该作为正式数据源。

### 4. 桌面 UI 不再依赖 `localhost:8777`

桌面模式下：

- SSH config CRUD 使用 Tauri command。
- 私钥选择使用原生文件选择器。
- MCP 安装使用 Rust command。
- 这些核心功能不需要启动 `backend.main` HTTP 服务。

HTTP API 可以保留给开发模式或兼容场景，但不应作为桌面 App 核心本地管理能力的依赖。

## Python 兼容性改造要求

当前 Python MCP server 通过服务模块间接依赖项目内固定路径。为了支持桌面 App 打包，需要允许通过环境变量指定运行时路径。

需要支持的环境变量：

```text
REMOTE_SSH_MCP_CONFIG_PATH=/Users/<user>/Library/Application Support/Remote SSH MCP/ssh_config
REMOTE_SSH_MCP_DATA_DIR=/Users/<user>/Library/Application Support/Remote SSH MCP/data
```

期望行为：

- 如果设置了 `REMOTE_SSH_MCP_CONFIG_PATH`，MCP 从该文件读取 SSH targets。
- 如果设置了 `REMOTE_SSH_MCP_DATA_DIR`，plans 和 audit logs 存储到该目录。
- 如果没有设置环境变量，可以保留当前仓库根目录行为作为开发期 fallback。

这是必须项，否则桌面 App 管理的是一份配置，而 MCP server 读取的是另一份配置，用户体验会割裂。

## 实施阶段

### 阶段 A：最小 Tauri 基础

目的：

创建能承载现有 `web` UI 的最小 Tauri 工程结构。

任务：

- 新增 `src-tauri/`。
- 配置 Tauri 使用现有 Vite 应用。
- 配置开发模式运行 Vite。
- 配置生产模式使用 `web/dist`。
- 确认 macOS App 能启动。
- 除必要 UI 渲染外，不迁移业务逻辑。

验收标准：

- `cargo tauri dev` 能打开桌面 App。
- 现有 UI 外壳能在 App 窗口中渲染。
- App 主题能跟随系统浅色/深色模式。
- App 启动不依赖 `backend.main`。

### 阶段 B：Rust 实现 SSH Config CRUD

目的：

用 Rust/Tauri command 替换 HTTP 版 SSH config CRUD。

Rust commands：

```text
list_ssh_configs() -> Vec<SshConfigEntry>
get_ssh_config(host: String) -> Option<SshConfigEntry>
create_ssh_config(payload: SshConfigPayload) -> SshConfigEntry
update_ssh_config(host: String, payload: SshConfigPayload) -> SshConfigEntry
delete_ssh_config(host: String) -> bool
import_ssh_config(path: String) -> ImportResult
export_ssh_config(path: String) -> bool
open_config_folder() -> bool
```

数据模型保持与当前前端兼容：

```text
host
hostname
user
port
type
IdentityFile
password
workdir
remarks
```

文件行为：

- 读写 App 数据目录里的 `ssh_config`。
- 文件不存在时自动创建。
- 写入前备份，例如生成 `ssh_config.bak`。
- 保持可读的 OpenSSH 风格格式。
- 不把密码保存进 `ssh_config`。

前端改造：

- 把 `web/src/api/config.ts` 里的 HTTP 请求替换成桌面模式下的 Tauri `invoke`。
- 尽量保留当前 `ConfigEditor` 页面体验。
- 校验规则保持与当前行为一致，必要时更严格。

验收标准：

- 用户可以在桌面 App 中创建、编辑、删除 SSH 配置。
- 修改持久化到 App 数据目录。
- 除非用户显式导入/导出，否则不修改仓库根目录 `ssh_config`。
- 不需要启动 HTTP 后端。

### 阶段 C：原生文件选择器和 SSH 连接测试

目的：

提升本地 App 中私钥选择和连接验证体验。

Rust commands：

```text
pick_private_key() -> Option<String>
test_ssh_connection(payload: SshConfigPayload) -> TestResult
```

私钥选择器：

- 使用原生文件选择对话框。
- 返回文件系统路径。
- 默认不复制私钥文件。
- 只把用户选择的路径写入 `ssh_config`。

SSH 测试方案：

第一版推荐：

- 使用系统 `ssh` 命令，配合 batch mode 和 timeout。
- 先不要在 Rust 里实现完整 SSH 协议。

后续可选：

- 如果系统 `ssh` 不够稳定，再评估 Rust SSH 库。

验收标准：

- 用户可以通过原生对话框选择私钥。
- 用户可以测试某个 SSH 配置是否可连接。
- 测试失败时返回可理解、可行动的错误信息。

### 阶段 D：MCP 客户端检测和安装

目的：

让桌面 App 能给支持的 MCP 客户端安装或更新 `remote-ssh-mcp` 配置。

第一版支持目标：

```text
Claude Desktop
Codex
Cursor
手动复制 JSON 兜底
```

Rust commands：

```text
detect_mcp_clients() -> Vec<McpClientStatus>
install_mcp(client: String) -> InstallResult
uninstall_mcp(client: String) -> InstallResult
get_mcp_json() -> String
open_mcp_config(client: String) -> bool
```

安装行为：

- 尽量检测已知 MCP 配置文件路径。
- 读取已有 JSON 配置。
- 合并 `mcpServers.remote-ssh-mcp`，不删除其他 server。
- 写入前创建备份。
- UI 展示将要安装的 command、args、env。
- 不能静默覆盖用户其他配置。

第一版 MCP config 形态：

```json
{
  "mcpServers": {
    "remote-ssh-mcp": {
      "command": "/Applications/Remote SSH MCP.app/Contents/Resources/python/bin/python",
      "args": [
        "/Applications/Remote SSH MCP.app/Contents/Resources/ssh_mcp_server.py"
      ],
      "env": {
        "REMOTE_SSH_MCP_CONFIG_PATH": "/Users/<user>/Library/Application Support/Remote SSH MCP/ssh_config",
        "REMOTE_SSH_MCP_DATA_DIR": "/Users/<user>/Library/Application Support/Remote SSH MCP/data"
      }
    }
  }
}
```

如果第一版还没有内置 Python runtime，安装器可以在开发测试阶段指向开发环境 Python 路径。但正式发布不能依赖开发者本机 venv。

验收标准：

- App 能展示各 MCP 客户端是否已安装 `remote-ssh-mcp`。
- App 能安装 MCP 配置且不移除已有 MCP servers。
- App 写入配置前会创建备份。
- 自动检测失败时，仍可复制手动 JSON。

### 阶段 E：打包发布

目的：

产出可分发的 macOS App。

打包目标：

```text
.app
.dmg
```

任务：

- 配置 Tauri bundle metadata。
- 选择 app identifier，例如 `com.remote-ssh-mcp.app`。
- 添加 App icon。
- 包含必要资源文件。
- 决定 Python runtime 打包方式。
- 验证 App 数据目录创建。
- 验证 MCP 安装路径指向稳定的 App 内资源。

Python runtime 打包方案：

方案 1，仅开发期：

- 使用系统 Python 或仓库 venv。
- 不适合正式分发。

方案 2，第一版生产候选：

- 在 App resources 中内置 Python runtime 和依赖。
- MCP config 指向内置 Python 和内置 `ssh_mcp_server.py`。

方案 3，长期方案：

- 用 Rust MCP 二进制替换 Python MCP。
- MCP config 直接指向打包后的可执行文件。

验收标准：

- 用户不 clone 仓库也能安装 App。
- App 可以管理 App 数据目录中的 SSH config。
- App 可以安装 MCP 配置，且配置指向稳定的打包路径。
- MCP 客户端安装后可以启动 `remote-ssh-mcp`。

## UI 范围

尽量复用当前 `web` 的 UI 风格和布局。

主题策略：

- App 默认跟随系统主题。
- macOS 切换浅色/深色模式时，App 颜色应同步变化。
- 不在第一版强制做独立主题切换开关。
- 如果保留手动主题设置，也必须提供 `System` 选项，并作为默认值。
- 颜色 token 应通过 CSS 变量或现有主题机制统一管理，避免页面内硬编码浅色或深色。

第一版桌面页面：

```text
SSH Config
MCP Install
Settings
Logs，可选
Plans，可选
```

建议第一版导航：

- SSH Config：CRUD、选择私钥、测试连接。
- MCP Install：检测客户端、安装/卸载、复制 JSON。
- Settings：App 数据目录、导入/导出配置、打开配置文件夹。

Plans 和 Logs 可以先隐藏或做只读，等 MCP 数据目录打通后再完整接入。

## 安全要求

- 不把真实用户 SSH config 作为默认数据打包。
- 除非用户明确选择导入/复制，否则不复制私钥文件。
- 不把 SSH 密码明文保存到磁盘。
- 修改 `ssh_config` 或 MCP 客户端配置前必须备份。
- MCP JSON 合并必须保守。
- 不删除无关 MCP servers。
- 写入前尽量展示准确配置路径。
- 安装或卸载 MCP 配置前需要用户明确确认。

## 风险

### Python 打包风险

把 Python runtime 打进 Tauri App 可行，但会增加打包复杂度。

缓解方式：

- 先保证开发路径可用。
- 单独定义生产打包策略。
- 等桌面 UX 稳定后再评估 Rust MCP 重写。

### MCP 客户端配置路径变化

Claude、Cursor、Codex 的 MCP 配置路径可能随版本和系统变化。

缓解方式：

- 做 best-effort 检测。
- 始终提供手动复制 JSON 兜底。
- UI 展示检测到的配置路径。

### App 数据和 MCP 数据割裂

如果桌面 App 写一份 `ssh_config`，MCP server 读另一份，用户会困惑。

缓解方式：

- 在 MCP 安装生产可用前，必须先支持 `REMOTE_SSH_MCP_CONFIG_PATH` 和 `REMOTE_SSH_MCP_DATA_DIR`。

### SSH 测试行为不稳定

不同机器上的系统 `ssh` 输出和行为可能不同。

缓解方式：

- 使用保守的命令参数。
- 设置 timeout。
- 返回简短 stderr 作为诊断信息。
- 不把连接测试作为保存配置的强制条件。

## 确认后推荐开发顺序

1. 添加 Tauri 工程基础。
2. 添加 Rust App 数据目录 helper。
3. 实现 Rust SSH config parser/writer。
4. 把 `ConfigEditor` 接到 Tauri commands。
5. 添加原生私钥选择器。
6. 添加系统 SSH 连接测试。
7. 给 Python MCP server 增加 config/data 环境变量路径支持。
8. 添加 MCP JSON 生成逻辑。
9. 添加 MCP 客户端检测、安装、备份、合并逻辑。
10. 配置 macOS 打包。
11. 验证干净机器安装流程。

## 第一版不做的事

- 完整 Rust 重写 MCP server。
- 完整 Rust SSH 执行引擎。
- Windows/Linux 打包。
- 云同步。
- 团队凭据共享。
- 自动后台 daemon。
- 静默安装 MCP。

## 确认清单

开始开发前，需要确认以下决策：

- 使用 Tauri/Rust 做桌面 App。
- 复用当前 React/Vite UI。
- 桌面 SSH config CRUD 不使用 HTTP 后端。
- 生产数据目录使用 `~/Library/Application Support/Remote SSH MCP/`。
- 第一版保留 Python MCP server。
- Python MCP server 增加环境变量路径支持。
- MCP 安装器必须备份并合并配置，不覆盖无关内容。
- 第一版优先打包 macOS。
