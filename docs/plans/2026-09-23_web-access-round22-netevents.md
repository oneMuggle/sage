# 网页访问 Round 22：渲染分支 Network 事件化（2026-09-23）

- **上游文档**：Round 5 SN3；Round 13 AB1（rendered_status Navigation Timing 补偿的已知局限）；Round 21 DL2（browser_events 扩展先例）
- **范围**：后端 only（browser_events.py + web_render.py + test_browser_events.py + test_web_render.py）

## 0. 结论速览

Round 13 的 AB1 用 Navigation Timing `responseStatus` 补偿 CDP 短连接收不到事件帧的限制，但
这只能取到**最终 hop** 的状态。R22 在 browser_events 常驻 WS 上增加可选的 target attach +
Network.enable，让 render_page 能通过事件获取**重定向链上每个 hop 的状态**——多跳 302 后
被反爬拦截的场景能看到中间状态码而非仅最终 200（Cloudflare JS challenge 常见模式）。

## 设计

1. `NetworkResponseTracker`：线程安全，`record(session_id, url, status)` +
   `last_document(session_id)`——仅记录 `type == "Document"` 的响应；
2. `_EventChannel.start()` 增加 `network_targets: set[str]` 参数（需 attach 的 target_id
   集合）：setDownloadBehavior 后逐 target 发 `Target.attachToTarget{flatten:true}` →
   用返回的 `sessionId` 发 `Network.enable`；后续事件帧带 `sessionId` → 分发给 tracker；
3. render_page 在 createTarget 后调 `ensure_network_tracking(session, target_id)`；
   wait_page_ready 完成后用 `get_tracked_response(session, target_id)` 优先取事件状态
   （比 Navigation Timing 更准，能看 302 中间 hop）；
4. Navigation Timing 逻辑保留作为兜底（事件通道不可用时不影响现有行为）。
