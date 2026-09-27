# 通过 MCP 远程访问本地工作区（Sage Workspace MCP Server）

> 日期：2026-09-26 · 状态：**草案，待评审**
> 分支：`feat/localbridge-p0-safety`（只提交方案；实现时每个里程碑单开 worktree）
> 参考：`reference/LocalBridge-Share/LocalBridge/src/{server,main,tunnel,jobs,files}.cjs`
> 前置文档：`docs/mcp-localbridge-reuse-analysis.md`、`docs/mcp-localbridge-files-parity.md`

## 1. 目标

让外部支持 HTTP MCP 的 Agent（Claude Code、Codex、ShunCode、网页端 Agent 等）通过一个 URL 访问 Sage 中指定的**本地工作区**，功能对标 LocalBridge 和本会话正在使用的 ShunCode Bridge：

- 浏览、搜索、读取工作区文件；
- 经授权后修改文件、执行命令；
- 选择性开放 Sage 的特色能力（Office Lint / 读取、记忆检索、Wiki）；
- 在本机回环地址上使用；也可以经 Cloudflare Quick Tunnel 开放到公网。

### 非目标

- 不做 Named Tunnel / 固定域名，不做 OAuth（第一版用路径 token）。
- 本方案不含远程桌面控制和 UIA（另立方案）。
- 不把 Sage 的 LLM 对话能力作为工具暴露出去（避免远程 Agent 调用本地模型额度）。

## 2. 现状与约束

| 事实 | 位置 | 影响 |
|---|---|---|
| 后端 FastAPI 0.109 + uvicorn，只监听 `127.0.0.1:8765` | `backend/main.py` | 可以复用同一进程 |
| 主 API 有进程级能力令牌中间件 | `backend/api/local_auth.py` | MCP 入口**不能**挂在主 app 上（远程 Agent 拿不到本机令牌，也不应拿到） |
| 已有手写的 Streamable HTTP MCP **客户端** | `backend/mcp/http_client.py` | 协议口径（2025-03-26）已在仓库落地，可以反向拿来做契约测试 |
| 没有官方 `mcp` Python SDK | `backend/requirements*.txt` | SDK 要求 Python ≥ 3.10，且依赖更新的 starlette/anyio，与 py38 和 fastapi 0.109 冲突，所以**服务端手写 JSON-RPC** |
| 工具注册表、风险等级、权限引擎、审批队列都已存在 | `backend/tools/registry.py`、`permissions.py`、`api/permission_routes.py` | 远程调用可以复用同一套工具实现和审批流程 |
| 文件工具已有版本号和凭据拦截，但存在结尾点、空格绕过等缺陷 | `backend/tools/file_guard.py`、`docs/mcp-localbridge-files-parity.md` | **远程暴露前必须先修** |

## 3. 架构

```
远程 Agent ──HTTPS──▶ cloudflared (Quick Tunnel, 可选)
                            │
                            ▼ http://127.0.0.1:<mcp_port>/mcp/<token>
┌─────────────────────── Sage Python 后端进程 ───────────────────────┐
│  Workspace MCP Listener（独立 uvicorn app / 独立端口，默认关闭）       │
│   · 路由 /mcp/{token} · /healthz                                      │
│   · Origin 拒绝 · token 常量时间比对 · 会话表 · 限流                     │
│   · JSON-RPC: initialize / ping / tools/list / tools/call / DELETE    │
│        │                                                              │
│        ▼  RemoteToolGateway（按工作区权限和远程策略包装）                 │
│   复用 backend/tools/*：file / edit / patch / search / bash / office   │
│        │                                                              │
│        ▼  审计（只记录事件、工具名、耗时和结果码；不记参数、正文和 token） │
└───────────────────────────────────────────────────────────────────────┘
        ▲ 主 API（带 local_auth）：工作区 CRUD / 权限开关 / 状态 / 急停
Electron 主进程：设置页“远程工作区” · cloudflared 进程管理 · 全局急停快捷键
```

### 关键决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 服务端实现位置 | **Python 后端**，而不是像 LocalBridge 那样放在 Electron | 工具实现都在 Python；放在 Electron 还得再代理一层 |
| 监听方式 | **独立端口**，默认 `127.0.0.1:8767`，可配置 | 与主 API 的 local_auth 和 CORS 完全隔离；关闭功能时端口不存在 |
| 协议实现 | 手写 JSON-RPC，`enableJsonResponse` 风格（一律返回 `application/json`，不返回 SSE） | 兼容 py38；LocalBridge 同样用 JSON 响应；现有客户端两种都能解析 |
| 隧道进程 | **Electron 管理** `cloudflared` | 子进程生命周期、托盘、复制地址这些 UI 都在 Electron |
| 认证 | 每个工作区一个 256 位随机 token 放在路径里（`/mcp/<hex64>`） | 与 LocalBridge 和 ShunCode 一致；会话 ID 不作为凭据 |

## 4. 工作区模型与存储

`$SAGE_USER_DATA_DIR/remote_workspaces.json`，用临时文件加 rename 原子写入，`{"version":1,"workspaces":[...]}`：

```json
{
  "id": "uuid", "name": "sage", "root": "E:/ProgrammingData/electron/sage",
  "token": "<hex64>", "enabled": true,
  "permissions": { "read": true, "write": false, "shell": false, "office": false, "memory": false },
  "approval": "auto | ask",
  "created_at": "...", "rotated_at": "..."
}
```

- 创建时对 `root` 做 realpath；拒绝磁盘根目录和用户主目录（沿用 LocalBridge 的 `main.cjs` 规则）。
- **只读是默认值**。写入、命令、Office、记忆各自单独开关；开启写入和命令时要在 UI 上二次确认，并明确提示“命令执行不是沙箱”。
- token 不经任何 API 返回给前端列表。只有点击“复制地址”时，由后端组好 URL 直接交给 Electron 写入剪贴板。
- 关闭某项权限、禁用工作区、重置 token 时，立即关闭该工作区的所有会话和后台命令（对应 `Bridge.revoke`）。
- token 目前以明文存储（与 LocalBridge 相同）。后续可以接入已有的 `credential_vault.py` 或系统钥匙串，作为 M5 的可选项。

## 5. 协议与会话

| 项 | 规格 |
|---|---|
| 入口 | `POST/GET/DELETE /mcp/{token}`、`GET /healthz`（不含任何工作区信息） |
| Origin | 带 `Origin` 头的请求一律返回 403（MCP 是服务器之间的调用，拒绝浏览器跨站访问） |
| 握手 | 没有 `Mcp-Session-Id` 时只接受 `initialize`，否则返回 400 `INITIALIZE_REQUIRED` |
| 会话 | `Mcp-Session-Id` 用 uuid4；会话必须属于同一个工作区，否则返回 404 `SESSION_NOT_FOUND`；闲置 30 分钟回收；全局最多 24 个 |
| 请求体 | 上限 768 KB；支持 JSON-RPC 批量请求（可选） |
| 方法 | `initialize`、`notifications/initialized`、`ping`、`tools/list`、`tools/call`；其他方法返回 -32601 |
| instructions | 在 initialize 中下发使用规则：先读后改、写入必须带 version、命令不是沙箱、超时后不盲目重放、范围不清楚时停下来问用户 |
| 错误语义 | 工具错误通过 `isError: true` 返回文本错误码（`PERMISSION_DENIED`、`ACCESS_REVOKED`、`version_conflict`、`PATH_DENIED` 等） |
| 限流 | 每个会话每秒不超过 20 次 `tools/call`；并发的 `tools/call` 放进线程池执行，超出上限的排队 |

## 6. 远程工具集

所有路径都是**相对于工作区根目录的路径**，并套用 LocalBridge `parts()` 等级的路径校验（见第 7 节）。远程场景下**不**应用 Sage 内部的 `allowed_paths` 放行规则。

| 工具 | 权限 | 实现复用 | 远程差异 |
|---|---|---|---|
| `connection_info` | — | 新增 | 返回版本、会话恢复说明、“不要重放写操作”等约定 |
| `workspace_info` | — | 新增 | 返回名称、各权限状态、`shellSandboxed:false` |
| `list_directory` | read | `ListDirTool` | 隐藏受保护条目和符号链接；最多 500 条 |
| `find_files` | read | `workspace_index` / glob | 结果限制在工作区内 |
| `search_files` | read | `codebase_search_tool` / ripgrep | 跳过受保护路径 |
| `read_file` | read | `ReadFileTool` | 返回 `version`；分页 |
| `write_file` | write | `WriteFileTool` | **`expected_version` 必填**（新建文件传 `"new"`），与 LocalBridge 一致 |
| `edit_file` / `apply_patch` | write | `EditTool` / `ApplyPatchTool` | 远程调用同样**必须**带 `expected_version` |
| `run_command` / `get_command_output` / `cancel_command` | shell | `bash_tool` 的进程树管理 | 任务归属于会话；最多 4 个并发；最长 120 秒；保留最后 64K 输出；Windows 下使用 PowerShell `-EncodedCommand` 加 UTF-8 |
| `office_read` / `office_lint` | office | 现有 office 工具 | 第一版只读；文件同样限制在工作区内 |
| `memory_search` / `wiki_search` | memory | 现有工具 | 默认关闭（记忆可能含隐私） |

远程场景把 `expected_version` 设为必填：这样既对齐了 LocalBridge 的安全语义，又不影响 Sage 内部的对话工具（内部保持可选）。

## 7. 安全模型

### 7.1 路径（远程专用，比内部更严格）

1. 只接受相对路径。拒绝绝对路径、`\\` 或 `/` 开头、控制字符和 `:`（NTFS 备用数据流），以及长度超过 1000 的路径。
2. 拒绝空段、`..`、以点或空格结尾的段，以及 Windows 保留名（`con`、`nul`、`com1` 等）。
3. 逐段 `lstat`，任何一段是符号链接或 junction 就拒绝；最后用 realpath 复核结果在根目录之内。
4. 受保护路径取 LocalBridge 规则与 `file_guard.py` 的**并集**：`.git`、`.ssh`、`.aws`、`.azure`、`.env*`、`credentials`、私钥和证书扩展名等。远程场景下 `.git` 读写都拒绝。
5. 上面 1 到 4 条作为 `backend/tools/remote_path.py` 的纯函数实现，同时回灌修复内部 `file_guard.py` 的结尾点、空格绕过（parity 文档 A1）。

### 7.2 写入

写入采用 parity 文档 A2 的流程：先写临时文件，替换前复核版本号，再原子 rename，并加进程内文件锁（`FILE_BUSY`）。

### 7.3 执行与审批

- `approval = "ask"` 时，远程的写入、命令调用进入**现有审批队列**（`permission_routes` 的 pending），由用户在 Sage UI 或 Telegram 网关上批准。审批超时（默认 120 秒）按拒绝处理。
- `approval = "auto"` 时直接执行，但 `bash_validation` 判定为 DESTRUCTIVE 的命令仍强制进入 ask。

### 7.4 急停与撤销

- 全局快捷键 Ctrl+Alt+Esc（Electron `globalShortcut`）与 UI 上的“全部急停”按钮效果相同：停止隧道、监听器进入 paused、拒绝所有调用、关闭会话、终止命令进程树。
- 急停后**不会自动恢复**；重启 Sage 也不会自动开放公网。

### 7.5 审计

- 写入 `remote_audit.jsonl`，超过 2 MB 轮转。字段为时间、工作区 ID、事件、工具名、耗时、结果码。
- 不记录参数、文件内容、命令文本和 token。日志里出现的 `/mcp/<hex>` 一律替换为 `[redacted]`。

### 7.6 明确告知用户的边界

- 命令执行不是沙箱，拥有当前 Windows 用户的全部权限。
- 公网地址等同于密码；Quick Tunnel 的地址在每次重建隧道后会变化。
- 路径黑名单不等于 DLP，不要共享含敏感资料的目录。

## 8. 公网隧道（Electron）

移植 `tunnel.cjs` 的逻辑到 `electron/remoteTunnel.ts`：

- 查找 `cloudflared`：依次检查 Program Files、Program Files (x86) 和 PATH。不自动下载安装。
- 从输出中解析 `https://*.trycloudflare.com`，直到出现 `Registered tunnel connection` 才视为就绪；启动超时 90 秒。
- 意外退出后按 1、2、5、10、30 秒退避重连；每 15 秒请求一次 `<url>/healthz` 做自检。自检失败只标记为 degraded，**不**因此更换地址。
- 地址变化时在 UI 上提醒：“旧地址已失效，请重新复制”。
- Win7 LTS 线暂不提供隧道（cloudflared 对 Win7 的支持不确定），只保留本机回环访问。

## 9. UI（设置 → 远程工作区）

- 工作区卡片：名称、根目录、状态、活跃会话数、各权限开关、审批模式、复制地址（本机地址或公网地址）、重置 token、移除。
- 顶部：监听器开关、端口、隧道状态和健康状况、“全部急停”、急停快捷键是否注册成功。
- 审计面板：最近 150 条事件。
- 文案遵循 LocalBridge 的授权确认口径（第 7.6 节）。

## 10. 里程碑

| 编号 | 内容 | 交付 | 依赖 |
|---|---|---|---|
| **M0** | 安全前置：parity 文档 A1（路径绕过）、A2（原子写和锁）、A3（受保护路径）；新增 `remote_path.py` | 纯函数加单元测试 | — |
| **M1** | 只读 MCP 服务：工作区存储、独立监听器、协议和会话、`connection_info`、`workspace_info`、`list_directory`、`find_files`、`search_files`、`read_file`；审计；后端管理 API | 可以在本机用 Claude Code 或 ShunCode 连接 `http://127.0.0.1:8767/mcp/<token>` | M0 |
| **M2** | 写入：`write_file`、`edit_file`、`apply_patch`（版本号必填）；撤销语义 | 写入契约测试 | M1 |
| **M3** | 命令：`run_command` 三件套、会话归属、并发上限、进程树清理 | 命令契约测试 | M1 |
| **M4** | Electron：设置页、复制地址、急停快捷键、cloudflared 隧道 | 可在公网访问 | M1 |
| **M5** | 审批模式 `ask`（接入审批队列和 Telegram）、Office 和记忆工具、token 加密存储 | — | M2、M3 |

每个里程碑单独开 worktree 和 PR；M0 可以直接接在当前分支上做。

## 11. 测试

- **单元测试**：路径校验表驱动（含结尾点和空格、`:`、保留名、junction），token 比对，会话过期和上限，权限撤销。
- **协议契约测试**：用仓库自带的 `backend/mcp/http_client.py` 作为客户端连接测试监听器，覆盖 initialize、tools/list、tools/call，以及 404 会话恢复。这样可以同时验证 Sage 客户端和服务端两侧的一致性。
- **安全回归**：带 Origin 返回 403；错误 token 返回 404 且耗时与正确 token 无明显差异；越界路径、符号链接、受保护路径都被拒绝；版本冲突不写入；撤销后工具调用返回 `ACCESS_REVOKED`；审计日志中不出现 token 或参数。
- **py38 测试**：M0 到 M3 的全部测试同时在 `sage-backend-py38` 环境下运行。
- **手工验收**：ShunCode 或 Claude Code 通过隧道连接，完成“读取 → 修改 → 运行测试”的完整闭环。

## 12. 待确认问题

1. 默认端口是否用 8767？是否允许用户改为监听 `0.0.0.0` 供局域网访问？（建议不允许，局域网需求走隧道）
2. 第一版远程工具范围：只做 M1 到 M3 的通用编码工具，还是一并纳入 Office 和记忆？
3. 审批模式的默认值：`auto`（与 LocalBridge 相同）还是 `ask`（更安全）？
4. Win7 LTS 线是否需要回移植 M0 到 M3（不含隧道）？
5. 远程写入是否强制要求版本号？（本方案建议强制）
