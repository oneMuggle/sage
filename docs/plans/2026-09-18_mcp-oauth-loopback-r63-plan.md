# r63 批次计划：MCP OAuth 切片 3b——loopback 回调监听 + 浏览器拉起编排

日期：2026-09-17（分支创建于 main@58df53ebb，含切片 1 #984 / 2 #989 / 3a #998）
文件面：新增 backend/mcp/oauth_loopback.py + 单测；零 UI 改动
（McpTab 授权按钮 + IPC 是切片 3c/最终收口）。

## 背景

切片 3a（#998）把回调等待抽象为注入的 `wait_for_callback` 协程。本批次
提供它的**真实实现**：本机 loopback HTTP 回听（RFC 8252 §7，127.0.0.1
随机端口）+ 浏览器拉起。redirect_uri 必须在注册/授权前确定，因此回听
先绑定端口拿到 redirect_uri，再交给 `authorize_mcp_server`。

## 交付

1. `LoopbackCallbackServer`：
   - `__init__` 即绑定 127.0.0.1:0（内核分配端口），后台线程跑
     http.server（stdlib，零依赖）；`redirect_uri` 属性形如
     `http://127.0.0.1:<port>/callback`；
   - `wait(timeout=300)`（async）：单次 GET /callback 即捕获完整 URL
     并返回；`/` 其它路径回 404；超时 → TimeoutError；响应页给用户
     「授权完成，请回到 Sage」提示（UTF-8 HTML，双码序无碍）；
   - `close()`：释放端口；`__enter__/__exit__` 支持 with。
2. `authorize_mcp_server_with_loopback(server_url, *, scope=None,
   resource=None, client_name="sage", http_get_json, http_post_json,
   open_url) -> TokenRecord`：
   - 起 loopback → `open_url(authorization_url)`（真实实现传
     `webbrowser.open`/Electron shell；测试用记录桩）→ 等回调 →
     调 `authorize_mcp_server` → finally close；
   - `open_url` 返回 False/抛错 → 立即取消等待并 close（不让用户对着
     白页死等）。
3. 单测：真实 HTTP GET 打进回听（urllib）验证捕获、404、with 语义、
   超时（缩短 timeout）、open_url 失败快速失败、with_loopback 全链路
   （fake discovery/register/token + fake open_url + 线程内真 GET）。

## 不做
- McpTab 授权按钮 / IPC 路由 / 401 触发自动重授权（切片 3c）。

## Win7 对齐
新功能，不 cherry-pick 到 release/win7。
