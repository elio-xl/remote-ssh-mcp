# SSH Config Editor — 界面设计文档

> **技术栈**: React 18 + shadcn/ui + Tailwind CSS + xterm.js  
> **主题**: 暗色优先  
> **品牌色**: 红色系 `#ef4444`（沿用现有 index.html）

---

## 目录

1. [设计系统](#1-设计系统)
2. [全局布局](#2-全局布局)
3. [页面设计](#3-页面设计)
4. [组件规范](#4-组件规范)
5. [状态管理](#5-状态管理)
6. [交互规范](#6-交互规范)
7. [响应式策略](#7-响应式策略)

---

## 1. 设计系统

### 1.1 色彩

基于 Tailwind CSS 变量 + shadcn/ui 的 CSS 变量体系，使用 Slate 灰色系 + 红色品牌色：

```
shadcn/ui 初始化参数:
  style: new-york
  base color: neutral
  css variables: yes
```

**语义色板**:

| Token | 用途 | 值 |
|-------|------|-----|
| `--primary` | 主操作按钮、选中态、链接 | `hsl(0, 84%, 60%)` (#ef4444) |
| `--primary-foreground` | 主色上的文字 | `hsl(0, 0%, 98%)` |
| `--background` | 页面背景 | `hsl(0, 0%, 7%)` (#121212) |
| `--card` | 卡片/面板背景 | `hsl(0, 0%, 10%)` (#1a1a1a) |
| `--border` | 分割线/边框 | `hsl(0, 0%, 15%)` |
| `--muted` | 次要文字 | `hsl(0, 0%, 45%)` |
| `--destructive` | 删除/危险操作 | `hsl(0, 84%, 60%)` |

**状态色**:

| 状态 | 色值 | 场景 |
|------|------|------|
| 已连接/成功 | `hsl(142, 71%, 45%)` (#22c55e) | 连接状态灯、审批通过、执行成功 |
| 警告/待审批 | `hsl(38, 92%, 50%)` (#eab308) | 计划待审批、连接超时 |
| 错误/断开 | `hsl(0, 84%, 60%)` (#ef4444) | 连接断开、审批拒绝、执行失败 |
| 信息/进行中 | `hsl(217, 91%, 60%)` (#3b82f6) | 连接中、执行中 |

### 1.2 排版

```
字体族:
  正文: Inter (system-ui 回退)
  代码: JetBrains Mono (monospace 回退)

层级:
  h1: text-3xl font-bold tracking-tight        (页面标题)
  h2: text-xl font-semibold                     (区块标题)
  h3: text-base font-medium                     (卡片标题)
  body: text-sm                                 (正文)
  caption: text-xs text-muted-foreground        (辅助信息)
  code: font-mono text-sm                       (命令/路径/配置)
```

### 1.3 间距与圆角

```
圆角:
  按钮/输入框: rounded-lg (8px)
  卡片/面板: rounded-xl (12px)
  弹窗: rounded-2xl (16px)

间距 (基于 4px 单位):
  紧凑: p-2 / gap-2 (8px)    — 表格单元格、标签
  标准: p-4 / gap-4 (16px)   — 卡片内边距、表单项间距
  宽松: p-6 / gap-6 (24px)   — 页面区块间距
```

### 1.4 阴影

```
卡片: shadow-sm (微妙层次)
弹窗: shadow-lg
终端面板: shadow-[0_0_60px_-15px_rgba(239,68,68,0.15)] (红色辉光，延续 index.html 风格)
```

---

## 2. 全局布局

### 2.1 布局结构

```
┌─────────────────────────────────────────────────────┐
│  Header (h-14)                                       │
│  ┌──────┬──────────────────────────────────┬──────┐ │
│  │ Logo │  remote-ssh-mcp          🟢 3 连接 │ 用户  │ │
│  └──────┴──────────────────────────────────┴──────┘ │
├────────┬────────────────────────────────────────────┤
│        │                                            │
│ 侧边栏  │           主内容区                          │
│ (w-56) │         <Outlet />                         │
│        │                                            │
│ ────── │                                            │
│ 📡 连接 │                                            │
│ 📝 配置 │                                            │
│ 🔑 凭据 │                                            │
│ 📋 计划 │                                            │
│ 📜 日志 │                                            │
│ >_ 终端 │                                            │
│ ────── │                                            │
│ ⚙️ 设置 │                                            │
│        │                                            │
├────────┴────────────────────────────────────────────┤
│  Status Bar (h-7)                                    │
│  🟢 dev-server · 3 活跃 · 最后操作: 2 分钟前          │
└─────────────────────────────────────────────────────┘
```

### 2.2 组件实现

```tsx
// src/components/Layout.tsx
import { Sidebar } from "./Sidebar";
import { StatusBar } from "./StatusBar";

export function Layout() {
  return (
    <div className="flex h-screen flex-col bg-background">
      <Header />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
      <StatusBar />
    </div>
  );
}
```

### 2.3 Header

```tsx
// 使用 shadcn/ui: 无额外组件，纯 Tailwind
<header className="flex h-14 items-center justify-between border-b border-border px-4">
  <div className="flex items-center gap-2">
    <Terminal className="h-5 w-5 text-primary" />
    <span className="font-bold text-lg tracking-tight">remote-ssh-mcp</span>
  </div>

  <div className="flex items-center gap-4">
    <ConnectionIndicator count={3} />
    <Button variant="ghost" size="icon">
      <Settings className="h-4 w-4" />
    </Button>
  </div>
</header>
```

`ConnectionIndicator` — 连接状态汇总组件：
```tsx
function ConnectionIndicator({ count }: { count: number }) {
  return (
    <div className="flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-3 py-1 text-xs text-emerald-400">
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
      </span>
      {count} 连接
    </div>
  );
}
```

### 2.4 Sidebar

```tsx
// 使用 shadcn/ui: ScrollArea + Badge
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const navItems = [
  { to: "/connections",  icon: Cable,     label: "连接",   badge: 3 },
  { to: "/config",       icon: FileEdit,  label: "配置"            },
  { to: "/credentials",  icon: KeyRound,  label: "凭据"            },
  { to: "/plans",        icon: Shield,    label: "计划",   badge: 2 },
  { to: "/logs",         icon: ScrollText,label: "日志"            },
  { to: "/terminal",     icon: Terminal,  label: "终端"            },
];

export function Sidebar() {
  const pathname = useLocation().pathname;

  return (
    <aside className="flex w-56 flex-col border-r border-border bg-card">
      <ScrollArea className="flex-1">
        <nav className="flex flex-col gap-1 p-3">
          {navItems.map(({ to, icon: Icon, label, badge }) => (
            <Link
              key={to}
              to={to}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                pathname === to
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground"
              )}
            >
              <Icon className="h-4 w-4" />
              <span className="flex-1">{label}</span>
              {badge != null && badge > 0 && (
                <Badge variant={pathname === to ? "default" : "secondary"} className="h-5 px-1.5 text-[10px]">
                  {badge}
                </Badge>
              )}
            </Link>
          ))}
        </nav>
      </ScrollArea>
    </aside>
  );
}
```

### 2.5 StatusBar

```tsx
// 纯 Tailwind，底部固定条
export function StatusBar() {
  return (
    <footer className="flex h-7 items-center justify-between border-t border-border bg-card px-4 text-xs text-muted-foreground">
      <div className="flex items-center gap-3">
        <span className="flex items-center gap-1">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          dev-server
        </span>
        <span>3 活跃</span>
      </div>
      <span>最后操作: 2 分钟前</span>
    </footer>
  );
}
```

---

## 3. 页面设计

### 3.1 连接管理 `/connections`

**功能**: 连接列表、新建连接、一键连接、断开、健康检查

```
┌─────────────────────────────────────────────┐
│  连接管理                     + 新建连接      │
├─────────────────────────────────────────────┤
│                                             │
│  ┌─ 搜索 ────────────────────────┬────────┐ │
│  │ 🔍 搜索连接...                │ 筛选 ▾  │ │
│  └───────────────────────────────┴────────┘ │
│                                             │
│  ┌─────────────────────────────────────────┐│
│  │ 🟢 dev-server                  ⋮ 菜单  ││
│  │   admin@192.168.1.100:2222              ││
│  │   密钥: dev_rsa · 活跃 34 分钟           ││
│  │   [断开] [健康检查] [终端]               ││
│  ├─────────────────────────────────────────┤│
│  │ ⚪ staging-db                  ⋮ 菜单  ││
│  │   root@10.0.2.15:3306                   ││
│  │   密钥: staging_ed25519 · 未连接         ││
│  │   [连接] [删除]                          ││
│  ├─────────────────────────────────────────┤│
│  │ 🟢 prod-web-01                ⋮ 菜单  ││
│  │   deploy@prod-web.internal:22           ││
│  │   跳板: bastion · 活跃 2 小时            ││
│  │   [断开] [健康检查] [终端]               ││
│  └─────────────────────────────────────────┘│
│                                             │
└─────────────────────────────────────────────┘
```

**shadcn/ui 组件**:

| 组件 | 用途 |
|------|------|
| `Table` | 连接列表（可选，卡片布局更好） |
| `Card` | 每个连接一个卡片 |
| `Badge` | 连接状态（已连接/断开） |
| `Button` | 操作按钮 |
| `DropdownMenu` | 每个卡片的 `⋮` 更多菜单 |
| `Input` | 搜索框 |
| `Dialog` | 新建连接弹窗（内部是表单） |
| `ContextMenu` | 右键菜单（连接/断开/编辑） |

**卡片组件示例**:

```tsx
function ConnectionCard({ conn }: { conn: Connection }) {
  return (
    <Card className={conn.connected ? "border-emerald-500/20" : "border-border"}>
      <CardHeader className="flex flex-row items-start justify-between pb-2">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <StatusDot status={conn.connected ? "online" : "offline"} />
            {conn.name}
            {conn.jumpDescription && (
              <Badge variant="outline" className="ml-1 text-[10px]">跳板</Badge>
            )}
          </CardTitle>
          <CardDescription>
            {conn.username}@{conn.hostname}:{conn.port}
          </CardDescription>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-8 w-8">
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem>编辑</DropdownMenuItem>
            <DropdownMenuItem>复制 SSH 命令</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem className="text-destructive">删除</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>密钥: {conn.keyName}</span>
          <span>·</span>
          <span>{conn.connected ? `活跃 ${conn.uptime}` : "未连接"}</span>
        </div>
      </CardContent>
      <CardFooter className="gap-2">
        {conn.connected ? (
          <>
            <Button variant="outline" size="sm" onClick={() => disconnect(conn.name)}>
              断开
            </Button>
            <Button variant="outline" size="sm" onClick={() => healthCheck(conn.name)}>
              健康检查
            </Button>
            <Button variant="outline" size="sm" asChild>
              <Link to={`/terminal?conn=${conn.name}`}>终端</Link>
            </Button>
          </>
        ) : (
          <Button size="sm" onClick={() => connect(conn.name)}>连接</Button>
        )}
      </CardFooter>
    </Card>
  );
}
```

### 3.2 SSH Config 编辑器 `/config`

**功能**: CRUD Host 条目（基于 `ssh-config-editor-crud.md` 设计文档）

```
┌─────────────────────────────────────────────┐
│  SSH Config  ~/.ssh/config    + 添加条目     │
├─────────────────────────────────────────────┤
│                                             │
│  ┌─ 左侧: 条目列表 ────┬── 右侧: 编辑区 ───┐ │
│  │                     │                   │ │
│  │ 🔍 过滤...          │  Host: dev-server │ │
│  │                     │                   │ │
│  │ ○ dev-server        │  ┌─ 表单 ───────┐ │ │
│  │   192.168.1.100     │  │ HostName     │ │ │
│  │                     │  │ 192.168.1.100│ │ │
│  │ ○ github.com        │  │              │ │ │
│  │   git@github.com    │  │ User         │ │ │
│  │                     │  │ admin        │ │ │
│  │ ○ prod-web-*        │  │              │ │ │
│  │   10.0.0.%h         │  │ Port         │ │ │
│  │                     │  │ 2222         │ │ │
│  │ ○ staging-db        │  │              │ │ │
│  │   10.0.2.1          │  │ IdentityFile │ │ │
│  │                     │  │ ~/.ssh/dev.. │ │ │
│  │ ○ * (全局)          │  │              │ │ │
│  │                     │  │ ProxyJump    │ │ │
│  │                     │  │ bastion      │ │ │
│  │                     │  │              │ │ │
│  │                     │  │ ── 高级 ──── │ │ │
│  │                     │  │ ☐ 压缩       │ │ │
│  │                     │  │ ☐ Agent 转发  │ │ │
│  │                     │  │ 保活: 60s    │ │ │
│  │                     │  │              │ │ │
│  │                     │  │ [保存] [取消] │ │ │
│  │                     │  └──────────────┘ │ │
│  └─────────────────────┴──────────────────┘ │ │
│                                             │
└─────────────────────────────────────────────┘
```

**布局**: 左右分栏（master-detail）

**shadcn/ui 组件**:

| 组件 | 用途 |
|------|------|
| `Table` | 左侧条目列表（带行选中高亮） |
| `Input` | 搜索过滤 |
| `Form` + `Input` | 编辑表单 |
| `Select` | 枚举字段（StrictHostKeyChecking、LogLevel 等） |
| `Switch` | 布尔字段（Compression、ForwardAgent） |
| `Button` | 保存/取消 |
| `Dialog` | 添加新条目弹窗 + 删除确认 |
| `Badge` | 条目类型标记（全局/模式/普通） |
| `Separator` | 高级选项分割 |
| `Tabs` | 可切换基础/高级表单标签页 |

**编辑表单核心字段**:

```
基础字段:
  Host             Input         必填，Host 别名/模式
  HostName         Input         目标主机名或 IP
  User             Input         SSH 用户名，默认 root
  Port             Input (number) 1-65535
  IdentityFile     Input + 添加按钮  多个私钥路径

高级字段 (折叠，默认隐藏):
  ProxyJump           Input         跳板机
  ForwardAgent        Switch        Agent 转发
  ServerAliveInterval  Input (number) 保活间隔
  StrictHostKeyChecking Select      主机密钥检查策略
  Compression         Switch        压缩
  RequestTTY          Select        TTY 分配
  RemoteCommand       Input         远程命令
  LocalForward        Input[]       本地转发
  Extra Directives    KeyValue 列表 自定义指令
```

**表单校验反馈**:

```tsx
// 使用 shadcn/ui 的 Form + react-hook-form 集成
<FormField
  control={form.control}
  name="port"
  rules={{
    min: { value: 1, message: "端口最小为 1" },
    max: { value: 65535, message: "端口最大为 65535" },
  }}
  render={({ field }) => (
    <FormItem>
      <FormLabel>Port</FormLabel>
      <FormControl>
        <Input type="number" {...field} />
      </FormControl>
      <FormMessage /> {/* 自动显示校验错误 */}
    </FormItem>
  )}
/>
```

### 3.3 凭据管理 `/credentials`

**功能**: 查看/删除已保存凭据、设置密钥认证

```
┌─────────────────────────────────────────────┐
│  凭据管理                      + 导入凭据     │
├─────────────────────────────────────────────┤
│                                             │
│  存储位置: ~/.ssh_mcp_credentials.json       │
│                                             │
│  ┌─────────────────────────────────────────┐│
│  │ 🔑 home-server               ⋮ 菜单    ││
│  │   admin@10.0.0.5:22                     ││
│  │   密钥: ~/.ssh_mcp_keys/home-server      ││
│  │   跳板: —                                ││
│  │   [连接] [导出到 Config] [删除]           ││
│  ├─────────────────────────────────────────┤│
│  │ 🔑 dev-box                    ⋮ 菜单    ││
│  │   dev@dev.example.com:2222              ││
│  │   密钥: ~/.ssh_mcp_keys/dev-box          ││
│  │   跳板: prod-bastion                     ││
│  │   [连接] [导出到 Config] [删除]           ││
│  └─────────────────────────────────────────┘│
│                                             │
└─────────────────────────────────────────────┘
```

**shadcn/ui 组件**: Card + Badge + Table + Button + Dialog（删除确认）+ DropdownMenu

### 3.4 计划审批 `/plans`

**功能**: 待审批计划列表、审批/拒绝/查看详情

```
┌─────────────────────────────────────────────┐
│  计划审批                     筛选: 全部 ▾   │
├─────────────────────────────────────────────┤
│                                             │
│  ┌─────────────────────────────────────────┐│
│  │ ⚠️ plan-a1b2c3    [待审批]   高风险      ││
│  │   dev-server · config_update             ││
│  │   Port: 2222 → 2223                      ││
│  │   + ServerAliveInterval 60               ││
│  │   过期: 2026-06-04 14:30                  ││
│  │   [查看详情]  [批准]  [拒绝]               ││
│  ├─────────────────────────────────────────┤│
│  │ ⚠️ plan-d4e5f6    [待审批]   中风险      ││
│  │   staging · config_add                   ││
│  │   新建条目 staging-db → 10.0.2.1:3306     ││
│  │   过期: 2026-06-04 15:00                  ││
│  │   [查看详情]  [批准]  [拒绝]               ││
│  └─────────────────────────────────────────┘│
│                                             │
└─────────────────────────────────────────────┘
```

**shadcn/ui 组件**:

| 组件 | 用途 |
|------|------|
| `Card` | 每个计划一个卡片 |
| `Badge` | 状态（待审批=黄 / 已批准=绿 / 已拒绝=红 / 已过期=灰）+ 风险等级 |
| `Button` | 批准/拒绝/查看详情 |
| `Dialog` | 计划详情弹窗（展示 diff + rollback plan） |
| `AlertDialog` | 拒绝确认（输入拒绝原因） |
| `Select` | 状态筛选 |
| `Tabs` | 按状态分标签页（待审批/已批准/已执行/已拒绝） |

### 3.5 审计日志 `/logs`

**功能**: 时间线视图、按事件类型过滤、按日期范围搜索

```
┌─────────────────────────────────────────────┐
│  审计日志        筛选: 全部事件 ▾  最近 50 条 │
├─────────────────────────────────────────────┤
│                                             │
│  ● 2026-06-02 14:32  PLAN_EXECUTED          │
│  │  plan-a1b2c3 · config_update · dev-server│
│  │  高风险 · 执行成功                        │
│  │  Port: 2222 → 2223, +ServerAliveInterval │
│  │                                          │
│  ● 2026-06-02 14:30  PLAN_APPROVED          │
│  │  plan-a1b2c3 · config_update · dev-server│
│  │  批准人: user · 批准备注: "确认端口变更"    │
│  │                                          │
│  ● 2026-06-02 14:25  PLAN_CREATED           │
│  │  plan-a1b2c3 · config_update · dev-server│
│  │  高风险 · 待审批                          │
│  │                                          │
│  ○ 2026-06-02 12:00  PLAN_EXPIRED           │
│  │  plan-x9y0z1 · command · prod-web-01     │
│  │  高风险 · 超时自动拒绝                    │
│                                             │
└─────────────────────────────────────────────┘
```

**shadcn/ui 组件**:

| 组件 | 用途 |
|------|------|
| `Table` | 时间线列表 |
| `Badge` | 事件类型标记（颜色区分） |
| `Select` | 事件类型 + 数量筛选 |
| `Input` | 搜索框 |
| `DatePicker` | 日期范围选择（需 `react-day-picker`） |

**事件类型颜色映射**:

```ts
const eventColors: Record<string, string> = {
  plan_created:   "bg-blue-500/10 text-blue-400 border-blue-500/20",
  plan_approved:  "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  plan_rejected:  "bg-red-500/10 text-red-400 border-red-500/20",
  plan_executed:  "bg-purple-500/10 text-purple-400 border-purple-500/20",
  plan_expired:   "bg-gray-500/10 text-gray-400 border-gray-500/20",
};
```

### 3.6 终端 `/terminal`

**功能**: xterm.js 远程 Shell，多标签页

```
┌─────────────────────────────────────────────┐
│  ┌─ 标签页 ───────────────────────────────┐ │
│  │ [dev-server ×] [prod-web ×]  [+ 新连接] │ │
│  └────────────────────────────────────────┘ │
│                                             │
│  ┌─────────────────────────────────────────┐│
│  │ admin@dev-server:~$ ls -la              ││
│  │ total 48                                ││
│  │ drwxr-x--- 6 admin admin 4096 Jun  2 ..││
│  │ -rw------- 1 admin admin  432 May 28 ..││
│  │                                         ││
│  │ admin@dev-server:~$ █                   ││
│  │                                         ││
│  │                                         ││
│  └─────────────────────────────────────────┘│
│                                             │
└─────────────────────────────────────────────┘
```

**shadcn/ui 组件**:

| 组件 | 用途 |
|------|------|
| `Tabs` | 多终端标签页 |
| `Select` | 选择已有连接 |
| `Button` | 新连接/关闭/复制/清屏 |
| `Badge` | 连接状态指示 |

**xterm.js 集成**:

```tsx
// src/pages/Terminal.tsx
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { useRef, useEffect } from "react";

type TerminalTab = {
  id: string;
  connectionName: string;
  label: string;
};

export function TerminalPage() {
  const terminalRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const [tabs, setTabs] = useState<TerminalTab[]>([
    { id: "1", connectionName: "dev-server", label: "dev-server" },
  ]);
  const [activeTab, setActiveTab] = useState("1");

  useEffect(() => {
    if (!terminalRef.current) return;

    const term = new Terminal({
      theme: {
        background: "#0a0a0a",
        foreground: "#e5e5e5",
        cursor: "#ef4444",
        selectionBackground: "#ef444440",
      },
      fontSize: 14,
      fontFamily: '"JetBrains Mono", monospace',
      cursorBlink: true,
      allowProposedApi: true,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(new WebLinksAddon());
    term.open(terminalRef.current);
    fitAddon.fit();

    // WebSocket 连接到后端
    const ws = new WebSocket(`ws://localhost:8777/ws/terminal?conn=${activeTabConnection}`);
    wsRef.current = ws;

    ws.onmessage = (event) => term.write(event.data);
    term.onData((data) => ws.send(data));

    termRef.current = term;

    return () => {
      ws.close();
      term.dispose();
    };
  }, [activeTab]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1 border-b border-border px-2">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              "flex items-center gap-1.5 border-r border-border px-3 py-2 text-xs",
              tab.id === activeTab
                ? "border-b-2 border-b-primary bg-card text-foreground"
                : "text-muted-foreground hover:bg-accent"
            )}
          >
            <StatusDot />
            {tab.label}
            <X className="ml-2 h-3 w-3 hover:text-destructive" />
          </button>
        ))}
        <Button variant="ghost" size="icon" className="h-6 w-6">
          <Plus className="h-3.5 w-3.5" />
        </Button>
      </div>
      <div ref={terminalRef} className="flex-1" />
    </div>
  );
}
```

---

## 4. 组件规范

### 4.1 通用组件清单

| 组件 | 文件 | shadcn/ui 源 | 说明 |
|------|------|-------------|------|
| `StatusDot` | `components/StatusDot.tsx` | 自定义 | 连接状态指示灯（绿/黄/红/灰） |
| `ConnectionCard` | `components/ConnectionCard.tsx` | Card + Badge + DropdownMenu | 连接卡片 |
| `PlanCard` | `components/PlanCard.tsx` | Card + Badge + AlertDialog | 计划卡片 |
| `ConfigEntryForm` | `components/ConfigEntryForm.tsx` | Form + Input + Select + Switch | SSH Config 编辑表单 |
| `EventTimeline` | `components/EventTimeline.tsx` | Table + Badge | 审计事件时间线 |
| `TerminalTabs` | `components/TerminalTabs.tsx` | Tabs + Button | 终端标签页管理 |
| `EmptyState` | `components/EmptyState.tsx` | 自定义 | 空状态占位图 |
| `ErrorBanner` | `components/ErrorBanner.tsx` | Alert | 全局错误提示 |

### 4.2 shadcn/ui 组件清单

需通过 `npx shadcn-ui@latest add` 安装的组件：

```
card          # 卡片容器
table         # 数据表格
form          # react-hook-form 集成
input         # 文本输入
select        # 下拉选择
switch        # 开关
button        # 按钮
badge         # 状态标签
dialog        # 弹窗
alert-dialog  # 确认弹窗（危险操作）
dropdown-menu # 下拉菜单
context-menu  # 右键菜单
scroll-area   # 自定义滚动条
separator     # 分割线
tabs          # 标签页
tooltip       # 悬停提示
toast         # 通知提示 (sonner 替代亦可)
sheet         # 移动端侧边抽屉
```

### 4.3 新建设计实现

**方案**: 弹出 Dialog + 表单

```tsx
<Dialog>
  <DialogTrigger asChild>
    <Button>
      <Plus className="mr-2 h-4 w-4" />
      新建连接
    </Button>
  </DialogTrigger>
  <DialogContent className="sm:max-w-[500px]">
    <DialogHeader>
      <DialogTitle>新建 SSH 连接</DialogTitle>
      <DialogDescription>
        输入连接信息。安全命令可直接执行，危险命令将创建审批计划。
      </DialogDescription>
    </DialogHeader>

    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
        <FormField name="connectionName" render={...} />
        <FormField name="hostname" render={...} />
        <FormField name="username" render={...} />
        <FormField name="port" render={...} />

        {/* 高级选项折叠 */}
        <Collapsible>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm">高级选项 ▾</Button>
          </CollapsibleTrigger>
          <CollapsibleContent className="space-y-4 pt-2">
            <FormField name="privateKeyPath" render={...} />
            <FormField name="jumpHost" render={...} />
            <FormField name="saveCredentials" render={...} />
          </CollapsibleContent>
        </Collapsible>

        <DialogFooter>
          <Button type="submit">连接</Button>
        </DialogFooter>
      </form>
    </Form>
  </DialogContent>
</Dialog>
```

---

## 5. 状态管理

### 5.1 方案

不引入 Redux/Zustand——利用 React Context + 自定义 hooks。

### 5.2 核心 Context

```tsx
// 连接状态
const ConnectionContext = createContext<{
  connections: Connection[];
  connect: (args: ConnectArgs) => Promise<void>;
  disconnect: (name: string) => Promise<void>;
  healthCheck: (name: string) => Promise<HealthStatus>;
} | null>(null);

// 计划状态
const PlanContext = createContext<{
  plans: ExecutionPlan[];
  approve: (planId: string, note?: string) => Promise<void>;
  reject: (planId: string, reason?: string) => Promise<void>;
  execute: (planId: string) => Promise<void>;
} | null>(null);

// SSH Config 状态（本地 CRUD）
const ConfigContext = createContext<{
  entries: SSHConfigEntry[];
  selectedHost: string | null;
  selectHost: (host: string) => void;
  addEntry: (entry: SSHConfigEntry) => Promise<void>;
  updateEntry: (host: string, entry: Partial<SSHConfigEntry>) => Promise<void>;
  deleteEntry: (host: string) => Promise<void>;
} | null>(null);

// WebSocket (终端 + 实时日志)
const WebSocketContext = createContext<{
  createTerminal: (connName: string) => WebSocket;
  subscribeLogs: (filter?: LogFilter) => WebSocket;
} | null>(null);
```

### 5.3 数据流

```
React Context (客户端状态)
       │
       ▼
Custom Hooks (useConnections, useConfig, usePlans, useLogs)
       │
       ▼
API Layer (fetch / WebSocket)
       │
       ▼
FastAPI Backend (localhost:8777)
```

---

## 6. 交互规范

### 6.1 加载态

```tsx
// 使用 shadcn/ui Skeleton 组件（需额外安装）
<Skeleton className="h-20 w-full" />
<Skeleton className="mt-2 h-20 w-full" />

// 或用 Tailwind animate-pulse 手写
<div className="space-y-3">
  <div className="h-20 animate-pulse rounded-xl bg-muted" />
  <div className="h-20 animate-pulse rounded-xl bg-muted" />
</div>
```

### 6.2 空态

```tsx
<EmptyState
  icon={<Cable className="h-12 w-12 text-muted-foreground/30" />}
  title="暂无连接"
  description="点击「新建连接」添加你的第一个 SSH 连接"
  action={<Button>新建连接</Button>}
/>
```

### 6.3 错误态

```tsx
// 全局错误 (顶部 Alert)
<Alert variant="destructive" className="mx-4 mt-2">
  <AlertCircle className="h-4 w-4" />
  <AlertTitle>连接失败</AlertTitle>
  <AlertDescription>Authentication failed — 请检查用户名和密钥</AlertDescription>
</Alert>

// 内联错误 (表单字段下方)
<FormMessage /> {/* shadcn/ui 自动处理 */}
```

### 6.4 乐观更新

```tsx
// 计划审批——先更新 UI，后台发请求
async function approve(planId: string) {
  setPlans(prev => prev.map(p =>
    p.planId === planId ? { ...p, status: "approved" } : p
  ));
  try {
    await api.approvePlan(planId);
  } catch {
    // 回滚
    setPlans(prev => prev.map(p =>
      p.planId === planId ? { ...p, status: "draft" } : p
    ));
    toast.error("审批失败，请重试");
  }
}
```

### 6.5 Toasts

```tsx
// 使用 sonner (比 shadcn/ui toast 更轻)
import { toast } from "sonner";

toast.success("已连接到 dev-server");
toast.error("连接超时");
toast("计划已创建，等待审批", {
  action: { label: "查看", onClick: () => navigate("/plans") },
});
```

---

## 7. 响应式策略

### 7.1 断点

```
默认 (≥1024px): 侧边栏 + 内容区，双栏布局
平板 (<1024px): 侧边栏折叠为顶部汉堡菜单 → Sheet
手机 (<640px):  单栏，卡片全宽
```

### 7.2 侧边栏响应式

```tsx
// 桌面: 固定侧边栏
<aside className="hidden lg:flex w-56 flex-col border-r">

// 移动端: Sheet 抽屉
<Sheet>
  <SheetTrigger asChild>
    <Button variant="ghost" size="icon" className="lg:hidden">
      <Menu className="h-5 w-5" />
    </Button>
  </SheetTrigger>
  <SheetContent side="left" className="w-56 p-0">
    <SidebarNav />
  </SheetContent>
</Sheet>
```

### 7.3 Config Editor 响应式

```
桌面 (≥1024px): 左右分栏 (w-64 列表 | flex-1 表单)
平板+手机 (<1024px): 列表全宽 → 点击进入详情页 (表单全宽)
```

### 7.4 连接卡片网格

```tsx
<div className="grid gap-4 sm:grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
  {connections.map(conn => <ConnectionCard key={conn.name} conn={conn} />)}
</div>
```

---

## 附录

### A. 项目文件结构

```
ui/
├── package.json
├── vite.config.ts
├── tailwind.config.js
├── postcss.config.js
├── index.html
├── src/
│   ├── main.tsx
│   ├── App.tsx                    # 路由配置
│   ├── index.css                  # Tailwind + shadcn/ui CSS 变量
│   ├── lib/
│   │   └── utils.ts               # cn() 工具函数
│   ├── components/
│   │   ├── ui/                    # shadcn/ui 组件 (自动生成)
│   │   ├── Layout.tsx
│   │   ├── Sidebar.tsx
│   │   ├── Header.tsx
│   │   ├── StatusBar.tsx
│   │   ├── StatusDot.tsx
│   │   ├── ConnectionCard.tsx
│   │   ├── PlanCard.tsx
│   │   ├── ConfigEntryForm.tsx
│   │   ├── EventTimeline.tsx
│   │   └── EmptyState.tsx
│   ├── pages/
│   │   ├── Connections.tsx
│   │   ├── ConfigEditor.tsx
│   │   ├── Credentials.tsx
│   │   ├── Plans.tsx
│   │   ├── Logs.tsx
│   │   └── Terminal.tsx
│   ├── hooks/
│   │   ├── useConnections.ts
│   │   ├── useConfig.ts
│   │   ├── usePlans.ts
│   │   ├── useLogs.ts
│   │   └── useWebSocket.ts
│   ├── contexts/
│   │   ├── ConnectionContext.tsx
│   │   ├── ConfigContext.tsx
│   │   └── PlanContext.tsx
│   └── api/
│       ├── client.ts              # fetch 封装 + base URL
│       ├── connections.ts
│       ├── config.ts
│       ├── plans.ts
│       └── logs.ts
└── public/
    └── favicon.svg
```

### B. 初始化命令

```bash
# 1. 创建 Vite + React 项目
npm create vite@latest ui -- --template react-ts
cd ui

# 2. 安装依赖
npm install react-router-dom @xterm/xterm @xterm/addon-fit @xterm/addon-web-links
npm install react-hook-form @hookform/resolvers zod sonner
npm install lucide-react
npm install -D tailwindcss @tailwindcss/vite

# 3. 初始化 shadcn/ui
npx shadcn-ui@latest init
# → New York style / Neutral base / CSS variables: yes

# 4. 添加 shadcn/ui 组件
npx shadcn-ui@latest add card table form input select switch button badge \
  dialog alert-dialog dropdown-menu context-menu scroll-area separator \
  tabs tooltip sheet
```

### C. 品牌引用

- 色板: [ui.jln.dev](https://ui.jln.dev) — shadcn/ui 主题生成器
- 图标: [lucide.dev/icons](https://lucide.dev/icons)
- 组件参考: [ui.shadcn.com](https://ui.shadcn.com)
