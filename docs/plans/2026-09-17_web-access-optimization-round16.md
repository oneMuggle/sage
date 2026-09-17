# 网页访问能力优化 Round 16：per-host 出网指标设置页展示（2026-09-17）

- **上游文档**：Round 15（metrics 端点已落地）；Round 12/14（凭据 UI 区块模式）
- **范围**：前端 only（消费既有 `GET /api/v1/web-access/metrics`）

## 设计

- `CredentialsSection` 增加出网指标展示：拉取 metrics，非空时按域名渲染
  `host — ok n / fail n / 升级 n / 均 x ms`；空则不渲染（避免噪音）。
- 指标为进程内存态（重启清零），文案明示；挂载时拉取一次。
- i18n zh/en 补键（`creds.metrics`、`creds.metrics.ok`、`creds.metrics.fail`、
  `creds.metrics.escalated`、`creds.metrics.avg`、`creds.metrics.empty`）。
