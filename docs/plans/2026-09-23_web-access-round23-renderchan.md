# 网页访问 Round 23：渲染池事件通道接线（2026-09-23）

- **上游文档**：Round 22（渲染分支 Network 事件化，#1403/#1431）；Round 5 SN3（事件通道先例）
- **范围**：后端 only（browser_events.py + web_render.py + 对应测试）

## 0. 结论速览

R22 验收后发现**生产路径缺口**：`start_download_tracking` 只在 browser_launch 工具
路径接线（browser_tool.py），渲染池 `_RendererPool.acquire` 直接 `launch_browser()`，
从不建立事件通道——`ensure_network_tracking` 在渲染分支永远拿不到 channel，
R22 批次 2 的事件状态优先**在生产上始终走 Navigation Timing 回退**。

R23 把这条线接上：渲染池建**纯事件通道**（跳过 `setDownloadBehavior`——渲染池
不落下载），此后 R22 的事件状态、302 中间 hop 可见性在渲染路径真实生效。

## 设计

1. `_EventChannel.start(setup_download: bool = True)`：`False` 时跳过
   setDownloadBehavior 握手直接进入读循环（下载事件本就以该命令为前提）；
2. 模块级 `start_event_channel(browser_id, port, ws_path) -> bool`：
   `DownloadTracker("")`（不落下载）+ `setup_download=False`；幂等（已连接复用）；
   失败面与 `start_download_tracking` 同口径——静默降级；
3. `render_page` 在 `_pool.acquire()` 后经 `_ensure_pool_channel(session)` 接线
   （尽力而为：通道失败不影响渲染，仅失去事件状态）；连接在池锁外进行，
   不阻塞并发渲染；
4. 池重建路径已闭环：`_discard → _terminate_session → stop_download_tracking`
   （browser_cdp 既有接线），下次渲染自动重连。

## 备忘（后续轮候选）

- AB3 TLS/HTTP2 指纹（main only，可选依赖 curl_cffi；win7 排除）——依赖引入
  需独立评估；
- 多实例渲染池（并发隔离/吞吐）；rendered_status 决策层已存在（web_tool
  `_ANTIBOT_STATUS_CODES` → 升级指引），无需重做。
