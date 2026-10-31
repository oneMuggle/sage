# P2：内置浏览器事件通道 + 应用内浏览器面板

> 基线：`release/win7`（P0 #2683、P1 #2689 已合并）。
> 目标：① embedded 浏览器恢复 CDP 事件通道（下载跟踪/渲染事件/arena 观测）；
> ② 应用内右栏「浏览器」面板（BrowserView），共享 `persist:sage-agent-browser` 登录态。

## 1. 背景

P1 的 embedded 桥只有 HTTP 命令通道，`browser_events` / `web_render` / arena 观测依赖
WebSocket CDP 事件，因此被降级为轮询/目录扫描/409。P2 在同一端口上增加 WS 升级：

- `ws://127.0.0.1:<port>/devtools/browser/embedded?token=…&session=<browser_id>&headless=0|1`
- WS 消息复用 `AgentBrowserBridge` 的命令分发（浏览器级 + sessionId → target）。
- 事件：`Page.loadEventFired`（did-finish-load）、`Network.responseReceived`（debugger message）、
  `Browser.downloadWillBegin/Progress`（session will-download）。

面板：右栏新增「浏览器」Tab，Electron `BrowserView` 挂到主窗口，bounds 由渲染层
`getBoundingClientRect` 经 IPC 同步；共享持久分区，用户可在面板内登录/浏览，
agent 通道立即复用同一会话。

## 2. 文件

| 文件 | 动作 |
|---|---|
| `electron/agentBrowserBridge.ts` | WS 升级/消息分发/事件订阅/download 事件发射 |
| `electron/agentBrowserHost.ts` | will-download 接线；BrowserView 创建/销毁/边界 |
| `electron/browserPanel.ts` | 新建：面板生命周期 + 安全硬化 |
| `electron/main.ts` / `preload.ts` / `src/shared/types/electron-api.d.ts` | IPC 注册与类型 |
| `src/features/right-panel/rightPanelStore.ts` | 新增 `browser` Tab |
| `src/features/browser/BrowserPanel.tsx` | 新建：地址栏/前进后退/刷新 + bounds 上报 |
| `src/widgets/chat/RightPanel.tsx`（右栏容器） | 挂载面板 |
| `backend/tools/browser_launcher.py` / `browser_cdp.py` | embedded ws_path 带 token/session；恢复事件通道 |
| `backend/tools/browser_tool.py` / `web_render.py` | 移除 embedded 跳过（改由 WS 通道工作） |
| `backend/api/arena_routes.py` | 移除 embedded 409（WS 可用） |
| `package.json` | 增加 `ws` + `@types/ws` |
| 测试 | WS 协议/面板 IPC/回归 |

## 3. 关键约束

- WS 升级必须校验 `token` + `session`；仅 127.0.0.1。
- WS 命令白名单与 HTTP 相同；sessionId=`sage-<targetId>` 只允许本 session 的目标。
- 事件只发给订阅该 target 的连接；连接断开清理监听。
- BrowserView：sandbox/contextIsolation/no node/共享分区/拒绝权限/仅 http(s)。
- 面板失焦/切换 Tab 时 `removeBrowserView`，避免遮挡。
- 面板 bounds 限制在主窗口内容区域内。

## 4. 任务

### Task 1：WS 事件通道（Electron）
- [x] 引入 `ws`；`startAgentBrowserBridge` 用 `WebSocketServer({noServer})` + upgrade 校验。
- [x] WS 命令：浏览器级走 dispatch；带 sessionId 解析 target 走 debugger。
- [x] 事件：Page.loadEventFired / Network.responseReceived / Browser.download*。
- [x] 单测：upgrade 鉴权、sessionId 路由、事件序列化。

### Task 2：后端恢复事件通道
- [x] embedded `ws_path` 带 token/session/headless。
- [x] 移除 `browser_tool` tracker 跳过、`web_render` 通道跳过、arena 409。
- [x] 单测：ws_path 形状、embedded 允许 tracker、渲染事件通道。
- [x] 真实 Electron 冒烟：Python websockets 连接、attach/enable、load 事件到达。

### Task 3：应用内浏览器面板
- [x] main/preload/types：`browserPanel.show/hide/setBounds/navigate/back/forward/reload/current`。
- [x] `BrowserPanel.tsx`：地址栏 + 控件 + ResizeObserver 上报 bounds；右栏 Tab。
- [x] 安全：BrowserView 硬化 + 仅 http(s) + 分区共享。
- [x] 测试：组件渲染/地址栏导航调用/bounds 上报；IPC 契约。
- [x] 真实 Electron 冒烟：panel 打开后导航到本地 fixture，cookie 与 embedded 共享。

### Task 4：验证与 PR
- [x] 后端相关测试 + `tsc`/eslint/vitest + py38 + architecture。
- [ ] PR → release/win7，CI 绿。

## 5. 风险

- WS 事件通道扩大本地接口面：token+session+命令白名单，错误连接直接销毁。
- BrowserView 在 Electron 21 可用但已废弃：P2 只做单视图，后续升级 Electron 时迁移 WebContentsView。
- 面板与 agent 窗口共享分区，可能同时操作同一站点：面板只用于用户登录/查看，agent 操作窗口独立。
