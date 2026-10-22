# Win7 批次 3 — MCP OAuth 端到端 + per-tool 面板对齐

> 目标：把 main 上 r53-B / r64 / r65 的 MCP OAuth 端到端 + per-tool 禁用面板同步到 release/win7，完成批次 2 留下的"OAuth 路由 + 前端 UI"缺口。

## 背景

批次 2（PR #2343，目标 release/win7）同步了 remote_mcp 子系统 + MCP OAuth 传输层核心（`backend/mcp/oauth.py`、`oauth_loopback.py`、`oauth_store.py`、`http_client.py`、`config.py` url 透传、`listener.py` 流式 body），但**未同步**：

- 后端 REST API（`/mcp/servers/{name}/tools`、`/mcp/servers/{name}/authorize`、`has_oauth_token` 字段）
- Electron IPC 路由（`mcp_server_tools`、`mcp_server_authorize`、`disabled_tools` 补丁）
- 前端 `mcpClient.ts`（类型、`serverTools()`、`authorizeServer()`）
- 前端 `McpTab.tsx`（per-tool 面板、授权按钮、🔑 角标）
- i18n key（`settings.mcp.authorize.*` 7 项）

缺口使批次 2 的 OAuth 传输层只能由 `http_client.py` 内部走（依赖外部工具注入 token），无法让用户从设置页主动发起授权。

## 缺口文件清单

| 文件 | 类型 | 行数差 |
|---|---|---|
| `backend/api/mcp_routes.py` | 后端 +116 行 | OAuth import / `has_oauth_token` 字段 / `GET .../tools` / `POST .../authorize` / 删除清理 token |
| `electron/commandRoutes/integrations.ts` | Electron IPC +2 路由 + PATCH body 补丁 | `mcp_server_tools` / `mcp_server_authorize` / `disabled_tools` |
| `src/shared/api/mcpClient.ts` | 前端 +36 行 | `disabled_tools` / `has_oauth_token` / `McpToolSpec` / `McpServerToolsReport` / `serverTools()` / `authorizeServer()` |
| `src/pages/settings/McpTab.tsx` | 前端 +194/-4 | per-tool 展开面板 + 授权按钮 + 🔑 角标 |
| `src/shared/lib/i18n/locales/en/chatAndSider.ts` | i18n +7 项 | `settings.mcp.authorize.*` |
| `src/shared/lib/i18n/locales/zh/chatAndSider.ts` | i18n +7 项 | `settings.mcp.authorize.*` |

## 依赖验证

- ✅ `backend/mcp/pool.py:McpServerPool.get_record(name)` 存在
- ✅ `backend/mcp/pool.py:ServerRecord.tool_specs` 字段存在
- ✅ `backend/mcp/oauth_store.py:OAuthTokenStore.has(name)` 存在
- ✅ `asyncio.run(...)`、`httpx.AsyncClient`、`webbrowser.open` 都是 Python 3.8 标准库或已装依赖

## 兼容性约束

- pydantic v1（release/win7 用 `requirements-py38.txt`）：`mcp_routes.py` 的新增代码用 `dict()` 而非 `model_dump()`，无新 pydantic 模型，纯 `dict` 响应
- Python 3.8 兼容：`asyncio.run` 标准库；`httpx` 已装；无 PEP 604 `|` 语法
- `architecture-check.mjs` baseline 更新：`mcp_routes.py` 行数增加 116，需重算 baseline
- i18n **只搬 mcp 段**（`settings.mcp.authorize.*` 7 项），不动 main 上其他非 mcp 增量

## 实施步骤

- [x] 步骤 1：在隔离 worktree 的 `feat/win7-batch3a-plugin-domain` 分支上实施（基于批次 2）
- [x] 步骤 2：后端 `backend/api/mcp_routes.py`（逐行对照 main 增量搬运）
- [x] 步骤 3：Electron IPC `electron/commandRoutes/integrations.ts`
- [x] 步骤 4：前端 `src/shared/api/mcpClient.ts`
- [x] 步骤 5：前端 `src/pages/settings/McpTab.tsx`
- [x] 步骤 6：i18n `en/chatAndSider.ts` + `zh/chatAndSider.ts`（仅 mcp 段）
- [x] 步骤 7：运行 `node scripts/architecture-check.mjs`；文件未超 800 行，无需更新 baseline
- [x] 步骤 8：后端测试（`sage-backend-py38` 环境）
  - [x] `backend/tests/api/test_mcp_routes.py`：覆盖 tools / has_oauth_token / delete 清理
  - [x] 新增 `backend/tests/unit/test_mcp_authorize_route.py`：覆盖 OAuth 授权成功、stdio 拒绝和未知服务器
  - [x] 32 个 MCP 路由测试通过
- [x] 步骤 9：前端测试；补齐 `McpTab.test.tsx` 并新增 `mcpClient.test.ts`，32 个用例通过
- [x] 步骤 10：静态门禁
  - [x] `ruff check backend/`
  - [x] `scripts/check_py38_compat.py`
  - [x] `node scripts/architecture-check.mjs`
  - [x] `npx tsc --noEmit`
- [ ] 步骤 11：commit + push + PR（目标 `release/win7`）
- [ ] 步骤 12：等 CI 绿（Backend py38 / Frontend TS / Electron build / smoke / architecture / count-lines）

## 风险评估

| 风险 | 影响 | 缓解 |
|---|---|---|
| `asyncio.run` 在 FastAPI 同步路由里运行，与已有 event loop 冲突 | 400 / OAuth 阻塞 | FastAPI 同步路由跑在 threadpool 里，每次调用独立 event loop，与 main 一致；不会冲突 |
| `httpx.AsyncClient` 超时 30s 不够 | OAuth metadata 发现失败 | main 已设计，沿用；用户反馈再调 |
| baseline 更新漏算 | architecture-check 红 | 跑 `--update-baseline` 后验证 diff |
| i18n 错搬 main-only 改动 | main 其他功能泄漏到 win7 | 只 grep `settings.mcp.authorize` 段精确提取 |

## 与批次 2 PR 的关系

PR #2343（批次 2，已合）是本 PR 的硬依赖：本 PR 的 `authorize_mcp_server` 路由调用 `authorize_mcp_server_with_loopback`、`get_oauth_token_store`、`ServerRecord.tool_specs` —— 这些都在 PR #2343 里落到 win7。顺序不可倒。
