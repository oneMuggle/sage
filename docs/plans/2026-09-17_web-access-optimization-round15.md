# 网页访问能力优化 Round 15：X2 延伸——per-host 出网指标 + 渲染 net 块（2026-09-17）

- **上游文档**：Round 5 §2.5 X2；Round 13（X2 net 块已落地 web_fetch）；Round 12（诊断/凭据 REST 模式）
- **范围**：main 与 release/win7 双分支（后端 only，零新依赖，py3.8 纪律）

## 0. 结论速览

X2 落地了单次调用的 net 块，但缺少**跨调用聚合**视角：某站点连续 403 / 升级率高，用户与
模型都无从感知。本方案在进程内维护 per-host 滚动指标（内存 ring，落库不加），经
`GET /api/v1/web-access/metrics` 暴露；渲染结果补齐 `net.elapsed_ms` 与静态口径对齐。

| 项 | 内容 | 批次 |
| --- | --- | --- |
| M1 | `web_metrics.py`：线程安全 per-host 滚动记录（ok/fail/escalated/avg_elapsed，容量 500/域名，总域名上限 200） | 批次 1 |
| M2 | web_fetch / http_download 埋点；渲染 render_page 补 `net.elapsed_ms` | 批次 1 |
| M3 | `GET /api/v1/web-access/metrics`（Origin 守卫同口径）；重置端点 PUT | 批次 2 |
| T | 单测 + 契约测试 + CHANGELOG | 批次 2 |

## 1. 设计要点

- key = url 的 host（idna 原样小写）；记录 `(ok: bool, escalated: bool, elapsed_ms: int)`；
  每域名 deque(maxlen=100)，全局域名 LRU 上限 200（超出淘汰最久未更新）。
- 埋点位置：web_fetch execute 成功/失败 return 前统一记录（RenderError/HTTPError 也算 fail）；
  http_download `_attempt` 完成处记录。escalated=成功且 content.get("escalated")。
- 指标为进程内存态，重启清零——定位为"诊断视角"而非审计；响应形如
  `{"metrics": {"example.com": {"ok": 12, "fail": 3, "escalated": 2, "avg_elapsed_ms": 831}}}`。
- 渲染 `render_page` 返回增加 `net: {elapsed_ms}`（与 web_fetch 的 net 键名对齐；web_tool
  合并 rendered 时会带出，同样不进缓存——需在 execute 的 storable 剥离已有 "net" 覆盖）。

## 2. 双分支

`web_metrics.py` 新文件 + web_tool / download_tool / web_render / web_access_routes 埋点 +
测试三处。全部同源文件，cherry-pick 零预期冲突。
