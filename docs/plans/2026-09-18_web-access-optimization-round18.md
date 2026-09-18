# 网页访问 Round 18：web_search 纳入 per-host 指标 + 指标 UI 刷新/重置（2026-09-18）

- **上游文档**：Round 15（web_metrics）、Round 16（指标 UI）

## 设计

- **S1**：`WebSearchTool.execute` 串行路径逐引擎埋点——伪域 `search:<engine>`，
  请求成功即 ok（0 条结果按 Round 9 口径仍记 ok）、异常记 fail；并行聚合模式
  暂不埋点（串行为默认路径，代码注释明示）。
- **U1**：指标区块加"刷新"（重新拉取）与"重置"（PUT metrics/reset 后刷新）按钮。
- 测试：假引擎注入 `resolve_engine_chain` 断言 `search:<name>` 指标；端点测试沿用。
