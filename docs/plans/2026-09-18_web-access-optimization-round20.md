# 网页访问 Round 20：并行聚合搜索指标 + 诊断导出集成（2026-09-18）

- **上游文档**：Round 18（串行搜索埋点，并行模式遗留）；Round 15（web_metrics）；Round 15-diag（诊断导出模式）

## 批次

1. **并行聚合指标收尾（R18 遗留）**：`_search_parallel` 成功路径对 `engines_used`
   逐引擎记 ok；失败/空结果路径对 errors 的引擎名记 fail（解析 `name: msg` 前缀）。
2. **诊断导出集成（X2 完整闭环）**：`diagnostic_routes.get_diagnostic_export`（或
   exporter 注入）把 `web_metrics.snapshot()` 写入 zip 内 `web-metrics.json`——
   支持人员拿诊断包即可见 per-host 出网成功率。
3. journey 测试 J4（并行搜索指标）+ CHANGELOG。

## 口径

- 并行成功（有结果）→ 每个 used 引擎记 ok；saw_completed 空结果 → 每个 used 记 ok
  （Round 9 口径：请求成功即 ok）；引擎异常 → fail。
- 指标快照写入 zip 用 json.dumps(ensure_ascii=False)；失败静默（诊断包不因指标失败而失败）。
