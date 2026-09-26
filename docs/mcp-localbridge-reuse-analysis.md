# LocalBridge 参考代码可复用能力分析

> 日期：2026-09-26
> 参考来源：`reference/LocalBridge-Share/`（LocalBridge Desktop 0.5.2 + LocalBridge-UIA）
> 目标：评估哪些功能可以引入 Sage。

## 1. LocalBridge 功能概览

| 模块 | 文件 | 能力 |
|---|---|---|
| MCP 服务端 | `LocalBridge/src/server.cjs` | Streamable HTTP MCP 服务，路径为 `/mcp/<256 位 token>`；每个工作区独立会话，最多 24 个会话，闲置 30 分钟回收；拒绝浏览器 Origin 访问；提供 `/healthz` 健康检查 |
| 公网隧道 | `LocalBridge/src/tunnel.cjs` | 自动查找 cloudflared 并启动 Quick Tunnel；按指数退避自动重连；每 15 秒自检公网健康；检测地址是否变更 |
| 文件工具 | `LocalBridge/src/files.cjs` | 路径 realpath 校验，禁止符号链接、junction、绝对路径和 `..` 跳转；屏蔽 `.env`、`id_rsa` 等常见凭据文件；写入需提交 SHA-256 版本号（乐观锁） |
| 命令任务 | `LocalBridge/src/jobs.cjs` | 按会话归属的后台任务，最多 4 个并发；PowerShell 用 `-EncodedCommand` 传入并强制 UTF-8；输出保留最后 64K；超时后终止整个进程树 |
| 桌面控制 | `LocalBridge/src/desktop.cjs`、`native/Desktop.cs`、`desktop-worker.*` | 窗口列表、独占租约（120 秒）、窗口截图、点击、拖拽、滚轮、Unicode 输入、组合键、`desktop_wait_window`；每次动作都校验 HWND、PID、标题和前台焦点；常驻 worker 降低延迟 |
| UIA 无障碍 | `LocalBridge/src/uia.cjs`、`native/uia.ps1`、`LocalBridge-UIA/` | 导出无障碍树、查找控件（名称 / AutomationId / 控件类型）、`uia_invoke`、`uia_set_value`、按控件中心点击；控件引用在会话内有效 |
| 急停与授权 | `LocalBridge/src/main.cjs` | 全局快捷键 Ctrl+Alt+Esc 急停；写入、命令、桌面、管理员权限分别授权，开启时弹原生确认框；可重置 token；审计日志写入 `audit.jsonl`，超过 2MB 轮转，不记录参数和正文 |
| 管理员代理 | `LocalBridge/admin/*.cs` | 以 SYSTEM 身份运行的 Broker 服务，只允许固定的诊断任务 |
| Python 客户端 | `LocalBridge/client/computer.py` | 以 Python 方式调用上述 computer-use 能力的客户端示例 |

## 2. Sage 现状对照

| 方面 | Sage 现状 | 缺口 |
|---|---|---|
| MCP | `backend/mcp/` 只有**客户端**（stdio / HTTP、OAuth、连接池、`mcp__server__tool` 命名空间） | 不能把 Sage 自身暴露为 MCP 服务 |
| 命令执行 | `bash_tool.py` 已有进程树清理、超时上限（600s）、30KB 输出上限；`permissions.py` 有四种权限模式和 bash 风险分级 | 基本齐全 |
| 文件写入 | `file_tool`、`edit_tool`、`patch_tool` 中没有 SHA-256 版本校验 | 缺少乐观并发控制 |
| 桌面自动化 | 只有浏览器 CDP（`browser_tool.py`），没有原生窗口或 UIA 能力 | 完全缺失 |
| 远程访问 | 有 Telegram / Discord / Slack 网关，用于远程对话和审批 | 没有让外部 Agent 直接调用工具的通道 |
| 急停 | `electron/crashGuard.ts` 里的 emergency 只是崩溃日志 | 没有全局急停快捷键 |
| 审计 | 有 `hooks/builtin_audit.py` | 需要确认是否已做到“不记录参数和正文”这样的脱敏 |

## 3. 建议引入的功能

### P0：成本低、收益明确

1. **SHA-256 乐观锁写入**（来源 `files.cjs`）
   - `read_file` 返回 `version`；`write_file` / `edit` / `patch` 可以带上 `expected_version`，新文件用 `"new"`。
   - 可以防止 Agent、子代理和用户同时编辑时互相覆盖。这与 Sage 的子代理并行编排直接相关。
   - 实现方式：在 `backend/tools/file_tool.py` 和 `edit_tool.py` 中增加一个可选参数，保持向后兼容。
2. **凭据路径黑名单与 junction 检查**（来源 `files.cjs`）
   - Sage 已有 `_is_safe_path` 和 `win_reparse_io.py`，可以补上 `.env`、`id_rsa`、`*.pem`、`.git-credentials` 等默认 deny 规则，挂到 `permissions.py` 的 deny 规则里。
3. **全局急停**（来源 `main.cjs`）
   - 在 Electron 主进程注册 `globalShortcut('Control+Alt+Escape')`，触发后端的 `pause`：取消所有正在运行的代理任务、终止 bash 进程树、释放桌面租约，并拒绝新的工具调用。
   - Sage 的 `api/orch_run_control.py` 已有运行控制，可以接在这里。

### P1：功能扩展

4. **Windows Computer Use / UIA 工具集**（来源 `desktop.cjs`、`uia.cjs`、`native/*`）
   - 这是 Sage 目前最大的能力空白，与 Office 写作场景直接相关：可以操作 WPS、Word 桌面版的对话框，以及无法用 COM 或 python-docx 完成的界面操作。
   - 优先复用 **UIA 语义层**（`uia_find_elements`、`uia_invoke`、`uia_set_value`），因为不依赖坐标，稳定性比截图加点击高。截图和坐标操作作为兜底。
   - 需要保留的安全设计：独占租约，每次动作校验 HWND、PID、标题和焦点，焦点变化即拒绝；单次输入最多 200 个字符；不操作 UAC 安全桌面；动作超时后不自动重放。
   - 接入方式有两种：
     - A. **作为外部 MCP 服务接入**（最快）：把 `LocalBridge-UIA/server.cjs` 登记到 `mcp_servers.json`，零改代码就能验证价值。
     - B. **原生移植**：在 `backend/tools/` 下新增 `desktop_tool.py`，通过常驻子进程调用 `uia.ps1` 和 `Desktop.cs`，纳入 `permissions.py`，新增一个 `DESKTOP` 能力级别，默认需要审批。
   - Win7 LTS 分支（Python 3.8 / Electron 21）需要单独验证 PowerShell 2.0 和 .NET 版本，建议只在 main 分支启用。
5. **命令输出编码处理**（来源 `jobs.cjs`）
   - PowerShell 用 `-EncodedCommand`（UTF-16LE base64）传入，并前置设置 `[Console]::OutputEncoding=UTF8`，从根上解决中文 Windows 下的乱码和引号转义问题；按流使用 `StringDecoder` 避免多字节字符被截断。可以对照 `shell_resolver.py` 看是否需要补。

### P2：新形态，需要产品决策

6. **把 Sage 作为 MCP 服务暴露（Sage-as-MCP-Server）**（来源 `server.cjs`、`tunnel.cjs`）
   - 让 Claude Code、Codex、ShunCode 等外部 Agent 调用 Sage 独有的能力：Office 生成和 Lint、记忆检索、知识库 RAG、GB/T 7714 引用。
   - 可以直接借鉴的做法：每个工作区一个 256 位 token 放在路径里；用 `timingSafeEqual` 比较；拒绝 Origin；限制会话数量并闲置回收；权限按工作区独立开关；撤销 token 后立即关闭会话和任务。
   - 后端是 Python，可以用官方 `mcp` Python SDK 的 Streamable HTTP 实现；也可以在 Electron 主进程用 `@modelcontextprotocol/sdk` 转发到 FastAPI。
7. **Cloudflare Quick Tunnel 管理**（来源 `tunnel.cjs`）
   - 只有做了第 6 项才需要。重连退避、健康自检、地址变更提示这些逻辑可以整体移植到 `electron/`。
   - 也可以作为 Telegram 网关之外的另一种远程通道。
8. **审计日志规范**：沿用 LocalBridge 的约定（只记录事件、工具名和耗时，不记录参数、正文和凭据；2MB 轮转），用来检查 `builtin_audit.py`。

### 不建议引入

- `admin/` 下的 SYSTEM Broker：只支持固定的诊断任务，却要安装服务并常驻高权限，风险和维护成本都高，与 Sage 的“透明可控”原则不符。
- `copy-settings`（复制地址时附加文字）和整套 LocalBridge UI：属于 LocalBridge 独有的交互，与 Sage 无关。

## 4. 推荐实施顺序

1. P0-1 乐观锁写入加 P0-2 凭据黑名单：约 1 天，附单元测试。
2. P1-4 方案 A：把 LocalBridge-UIA 作为外部 MCP 接入，在 Office 场景试用。
3. P0-3 全局急停：在做原生桌面控制之前必须具备。
4. P1-4 方案 B：原生 `desktop_tool.py` 加 `DESKTOP` 权限级别。
5. P2：评估 Sage-as-MCP-Server 的需求后再决定是否做。

## 5. 许可证与合规

需要确认 LocalBridge-Share 的许可证是否允许将代码并入以 MIT 发布的 Sage。在确认之前，只参考设计、重新实现，不直接复制代码。
