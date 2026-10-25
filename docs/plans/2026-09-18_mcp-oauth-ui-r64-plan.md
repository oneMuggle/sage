# r64 批次计划：MCP OAuth 收口——授权 API 路由 + IPC + McpTab 授权按钮

日期：2026-09-17（分支创建于 main@a513d0a88，含切片 1-3b：#984/#989/#998/#1039）
文件面：backend/api/mcp_routes.py（+1 路由）、mcpClient/commands.ts、
McpTab.tsx、i18n；测试三侧。

## 背景

OAuth 四切片的后端链路已全部就绪（纯函数 → token 持有 → 编排 → loopback
回听），但用户没有任何入口触发授权。本批次收口：HTTP 传输的 MCP 服务器
在设置面板出现「授权」按钮 → 后端起 loopback + 拉起系统浏览器 → 用户在
浏览器完成登录 → 回调捕获 → token 入库（切片 2 的注入/刷新链路即刻生效）。

## 交付

1. 后端 `POST /api/v1/mcp/servers/{name}/authorize`（mcp_routes.py）：
   - 仅 HTTP 传输（config.url 非空）→ 否则 400；
   - 同步路由（FastAPI 线程池跑，阻塞等待属预期）：webbrowser.open 拉起
     + httpx 直连发现/注册/交换端点 + loopback 等待（上限 300s）；
   - 成功 → TokenRecord 存 get_oauth_token_store() → 响应
     {ok, server, token_type, expires_at}（不回传 token 本体）；
   - 失败（超时/元数据/注册）→ JSONResponse 400 + 错误串（浏览器侧
     已给用户提示页，错误回到设置面板内联展示）；
   - 未知服务器 → 404。
2. 前端：
   - `commands.ts`：`mcp_server_authorize` POST（name 进路径）；
   - `mcpClient.authorizeServer(name)`；
   - `McpTab`：HTTP 服务器行（srv.url 非空）在启用开关旁加「授权」
     按钮 → 点击置 authorizing 态（按钮禁用 + 文案"授权中…"）→
     成功后刷新状态表 + 行内显示"已授权"角标（store 有记录）；
     失败内联错误。
   - i18n zh/en：settings.mcp.authorize.* 5 键。
3. 后端测试：respx 假发现/注册/交换端点 + monkeypatch webbrowser.open
   + 线程内真 GET 回调（r63 全链路测试同款）走 TestClient；
   另覆盖 400（stdio）/404/浏览器拒绝。

## 不做
- 401 自动重授权调度（后续按需）；token 明文展示（安全上永远不展示）。

## Win7 对齐
新功能，不 cherry-pick 到 release/win7。
