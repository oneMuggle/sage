# R102 批次计划 —— HttpClientMcpClient OAuth 注入/刷新/自愈测试

日期：2026-09-22 ｜ worktree：`.worktrees/feat-r102-mcp-http-tests`（基于 origin/main 671767c5）

## 背景

`backend/mcp/http_client.py`（338 行，Streamable-HTTP MCP 传输）的 OAuth 面
（r61/r70）无直接测试：token 注入覆盖静态头、过期同步刷新回存、401 自愈清除。
构造器显式支持 `http_client` 注入（httpx.MockTransport），测试面齐备。

## 批次内容

新增 `backend/tests/unit/mcp/test_http_client_oauth.py`（7 用例）：

1. initialize 握手捕获 `Mcp-Session-Id` 并在后续请求回传；Accept 双类型头；
2. 过期 token + 可刷新 → 刷新端点（form 编码）被调用、新 token 覆盖静态
   Authorization 头、新记录回存、refresh_token 未轮换时保留原值；
3. 过期但不可刷新 → 匿名继续（无 Authorization）；
4. 401 且带 token → 清除 store 记录并抛"重新授权"点名错误；
5. 401 且无 token → 普通 MCP HTTP 错误（无"重新授权"字样、无删除）；
6. 无 OAuth 记录时静态 `Authorization: Bearer pat` 头正常携带；
7. 已建会话遇 404 → session expired 识别并复位运行态。

fake store（load/save/delete 鸭子类型）注入，进程级单例不触达。

## 验证矩阵

- 本机：py_compile + CI 同款 ruff 0.4.4 全过（F401/PT018 已修）。
- CI：Backend (Python) pytest 全量（MockTransport 纯内存，无网络）。

## 不做

- SSE 解析路径（`_parse_sse`）留待后续批次；不改生产代码。
