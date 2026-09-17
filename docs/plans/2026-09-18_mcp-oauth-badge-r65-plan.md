# r65 批次计划：MCP OAuth 状态可见化——has_oauth_token + 授权角标

日期：2026-09-17（分支创建于 main@30a800936，含 r64 #1056）
文件面：mcp_routes.py（status/servers 响应加字段）、oauth_store（+has）、
mcpClient/McpTab、i18n；三侧测试。

## 背景

r64 之后用户点「授权」能看到成功提示，但重启设置页后无从得知某台
HTTP 服务器是否已授权（token 在库里没有可见面）。授权状态还影响行为
语义（无 token = 匿名调用，有 token = 带凭据调用）。

## 交付

1. 后端：
   - `GET /mcp/status` 的 per-server entry 增 `has_oauth_token: bool`
     （从 OAuthTokenStore 读，读失败按 false）；
   - `GET /mcp/servers` 的 config dict 增同名字段；
   - `DELETE /mcp/servers/{name}` 顺带清理该服务器的 token 记录
     （删除服务器不留孤儿凭据——与 r56 失联记忆清理同哲学）。
2. 前端：
   - `McpServerStatusEntry.has_oauth_token` 类型；
   - McpTab：已授权的 HTTP 服务器名旁渲染钥匙角标 🔑（title 提示
     「已 OAuth 授权」），授权按钮在已授权时改文案为「重新授权」。
   - i18n zh/en：settings.mcp.authorize.badge / reauthorize 2 键。
3. 测试：
   - 后端：status/servers 响应含字段（有/无 token 两态）；
     delete 清理 token；
   - 前端：角标渲染 + 重新授权文案（mock）。

## 不做
- token 明文/过期时间展示（安全边界）；自动重授权调度。

## Win7 对齐
新功能，不 cherry-pick 到 release/win7。
