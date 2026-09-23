# 网页访问 Round 25：事件命中率可视化 + 渲染池槽位配置化（2026-09-23）

- **上游文档**：Round 22（#1403/#1431）；Round 23（#1442/#1447）；Round 24（#1453/#1463）
- **范围**：后端 + 前端（web_render.py / settings_repo KEY 不变 / NetworkTab.tsx + i18n + 测试）

## 0. 结论速览

R24 在 metrics 快照里加了 `render_events` 全局键，但设置页把 metrics 当
"host → 指标"表渲染——`render_events` 会以**假域名行**混进域名列表（回归）。
R25 批次 1 修复并顺势把命中率做成独立可视化块；批次 2 把渲染池槽位数从
常量改为 `web_access_config.render_pool_size`（默认 2，钳 1..4）。

## 设计

### 批次 1：NetworkTab 修复 + 命中率块

- `HostMetrics` 类型收窄为纯 host 表；`render_events` 从 host 循环里过滤；
- 新增独立块 `data-testid="render-events-metrics"`：渲染数 / 通道就绪 /
  事件命中 三计数（无数据即 renders=0 时隐藏）；
- i18n：`settings.network.creds.metrics.render_events` 系列键（zh/en）；
- vitest：mock `/web-access/metrics` 返回 host + render_events 混合载荷，
  断言假域名行不出现、命中率块出现且计数正确。

### 批次 2：render_pool_size 配置化

- `web_render._render_pool_size()`：读 `web_access_config.render_pool_size`
  （int，钳 1..4，默认/异常回退 `RENDER_POOL_SIZE`=2）——沿用
  `_auto_refresh_enabled` 的静默容错口径；
- `_RendererPool.acquire`：槽位数不足配置值时懒增槽（id 沿
  `render-pool`/`render-pool-{n}` 前缀约定，browser_cdp.get(None) 排除逻辑
  天然覆盖）；配置缩小不回收已活实例（LRU 自然少用）；
- 前端 `WebAccessConfig` 增 `render_pool_size`（默认 2），设置页凭据卡给
  1..4 下拉；i18n 补键；
- 后端测试：解析钳位/回退；acquire 懒增槽（配置 3 → 第三个 acquire 用
  `render-pool-3`）。

## 备忘（后续轮候选）

- 全量单测疑似泄漏 ~20 个 chrome 进程（ephemeral profile 未回收）——
  独立排查轮；
- AB3 TLS/HTTP2 指纹（curl_cffi，main only）——依赖引入独立评估。
