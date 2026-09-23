# 网页访问 Round 24：渲染池生产化——多实例 + 事件命中率可观测（2026-09-23）

- **上游文档**：Round 22（Network 事件化 #1403/#1431）；Round 23（渲染池事件通道接线 #1442/#1447）
- **范围**：后端 only（browser_cdp.py / web_render.py / web_metrics.py + 对应测试）

## 0. 结论速览

R22/R23 把渲染分支的 Network 事件状态打通后，渲染池自身的两个生产化短板浮出：

1. **单实例**：所有并发渲染共用一个浏览器进程——重页面把进程拖垮时，
   全部 in-flight 渲染一起失败；实例级崩溃隔离与内存余量都没有；
2. **不可观测**：事件状态是否真的在生产命中（通道建立率 / 事件命中率）
   无从验证——R23 的接线效果只能靠信念。

R24 批次 1 把渲染池扩成多槽 LRU（并发 acquire 自然分散到不同实例），
批次 2 给 web_metrics 加渲染事件命中率计数（诊断导出可见）。

## 设计

### 批次 1：多实例渲染池

- 槽位 id：`RENDER_POOL_IDS = (RENDER_POOL_ID, "render-pool-2")`——槽 1 沿用
  既有保留 id（`RESERVED_BROWSER_ID`，兼容既有引用/测试），槽 2 新增；
  `RENDER_POOL_SIZE = 2` 保持保守；
- `browser_cdp.get(None)` 的"用户实例"解析在精确排除 `RESERVED_BROWSER_ID`
  外，追加排除 `render-pool-` 前缀——否则槽 2 的存在会破坏单用户浏览器
  免传 id 的便利解析（get(None) 变 None → 工具报"必须传 browser_id"）；
- `_RendererPool.acquire`：持锁按 last_used LRU 选槽（并发 acquire 自然
  分散）；槽内会话存活且未过空闲超时则复用；否则丢弃重建。启动失败时
  按 LRU 序降级试下一槽，全部失败才抛 RenderError；
- 事件通道接线（R23 `_ensure_pool_channel`）不变：按会话 browser_id 幂等，
  槽重建后经既有 `stop_download_tracking` 清理、自动重连。

### 批次 2：渲染事件命中率指标

- `web_metrics.record_render_event(channel_ok: bool, tracked_hit: bool)`：
  进程内全局计数 `{renders, channel_ok, event_status_hits}`；异常静默；
- `snapshot()` 增 `render_events` 键（诊断视角，前端可后续接入）；`reset()` 一并清零；
- `render_page` 埋点：渲染即 attempts+1；`_ensure_pool_channel` 成功
  channel_ok+1；事件状态被采用（tracked 有 Document 记录）hits+1。

## 备忘（后续轮候选）

- AB3 TLS/HTTP2 指纹（main only，可选依赖 curl_cffi；win7 排除）——依赖
  引入需独立评估；
- 渲染池槽位数暴露为 web_access_config 配置（当前常量 2 够用）；
- 事件驱动就绪等待（Page.loadEventFired 替代 readyState 轮询）——轮询
  粒度 0.3s，收益 ~0.3-0.5s/渲染，优先级低。
