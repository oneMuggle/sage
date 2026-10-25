# Workspace MCP Server — M4：Electron 隧道 / 急停 / 设置页

> 上位方案：`docs/plans/2026-09-26-workspace-mcp-server.md` §7.4、§8、§9、§10(M4)
> 依赖：#1637（M1–M3，`backend/remote_mcp/`）
> 参考：`reference/LocalBridge-Share/LocalBridge/src/{tunnel,main}.cjs`

## 1. 范围

| 做 | 不做（M5 或以后） |
|---|---|
| `electron/remoteTunnel.ts`：cloudflared Quick Tunnel 进程管理 | 自动下载 cloudflared |
| `electron/remoteMcpIpc.ts`：隧道 / 急停 / 复制地址 IPC | 审批模式 `ask`、Office / 记忆工具 |
| 全局急停快捷键 Ctrl+Alt+Esc | token 加密存储 |
| 设置 → 远程工作区 Tab（监听器、隧道、工作区卡片、审计） | Named Tunnel / 固定域名 |
| `commands.ts` 路由：`remote_mcp_*` | 局域网 `0.0.0.0` 监听 |

## 2. 设计

### 2.1 隧道（主进程）

- 移植 `tunnel.cjs`：`start(port)` 启动 `cloudflared tunnel --no-autoupdate --url http://127.0.0.1:<port>`。
- 从 stdout/stderr 解析 `https://*.trycloudflare.com`（排除 `api.trycloudflare.com`），出现 `Registered tunnel connection` 才算就绪；90 秒启动超时。
- 意外退出按 1/2/5/10/30 秒退避重连；`ENOENT`（没装 cloudflared）为致命错误，不重试。
- 每 15 秒自检 `<url>/healthz`，要求 `service === "SageWorkspaceMCP"`；失败只标记 `degraded`，**不**换地址。
- 地址变化时 `addressChanged = true`，UI 提示“旧地址已失效，请重新复制”；复制后清除。
- 可执行文件查找：Program Files、Program Files (x86)、PATH。不自动下载。
- Win7 LTS（`isLegacyWindows()`）：`tunnelSupported = false`，启动直接报错。
- Node 16 兼容：不用 `AbortSignal.timeout`，fetch 走 `fetchCompat`。

### 2.2 IPC（全部经 `isTrustedRenderer` 校验、演示模式拒绝）

| 通道 | 行为 |
|---|---|
| `remote-mcp:tunnel-state` | 返回隧道快照（state/url/error/health/addressChanged/retryCount/supported/hotkeyRegistered） |
| `remote-mcp:tunnel-start` | 先要求后端监听器在运行且未急停；再 `tunnel.start(listener.port)` |
| `remote-mcp:tunnel-stop` | 停隧道 |
| `remote-mcp:emergency-stop` | 停隧道 + `POST /api/v1/remote-mcp/emergency-stop`（后端失败也保证隧道已停） |
| `remote-mcp:copy-url(id, {public})` | 调后端 `connection-url`（公网时带 `public_base`），**直接写剪贴板**，token 不回到渲染进程 |

### 2.3 急停快捷键

- `app.whenReady` 后注册 `Control+Alt+Escape`，与“全部急停”按钮同一函数；注册失败（被占用）时 UI 显示“快捷键未注册”。
- `before-quit`：注销快捷键、停隧道。
- 急停后不自动恢复；重启 Sage 也不自动开隧道。

### 2.4 设置页 Tab `remote-workspaces`

- 顶部：监听器开关 + 端口、隧道开关 / 状态 / 健康、“全部急停”、快捷键状态、急停后的“恢复”。
- 工作区卡片：名称、根目录、会话数、启用开关、权限开关（read/write/shell；write/shell 开启需二次确认，文案“命令执行不是沙箱”）、复制本机 / 公网地址、重置 token、移除。
- 审计：最近事件（后端 `audit.recent()`）。
- 边界文案（§7.6）：命令不是沙箱；公网地址等于密码；黑名单不等于 DLP。
- 每 3 秒轮询 `state` 与 `tunnel-state`（页面可见时）。

## 3. 测试

- `electron/__tests__/remoteTunnel.test.ts`：注入假 spawn / fetch：就绪解析、排除 api 域名、超时、ENOENT 不重试、意外退出退避重连、地址变化标记、health degraded 不换地址、stop 幂等。
- `electron/__tests__/remoteMcpIpc.test.ts`：tunnel-start 要求监听器运行；emergency 在后端失败时仍停隧道；copy-url 写剪贴板且返回值不含 token；Win7 拒绝。
- `commands.test.ts` 自动覆盖新增路由的路径拼接。
- 设置页组件测试：渲染、开启 shell 需确认。
- 手工验收：本机 cloudflared → Claude Code / ShunCode 走公网地址完成“读 → 改 → 跑测试”；Ctrl+Alt+Esc 后远端调用全部失败。
