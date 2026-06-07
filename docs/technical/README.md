# 技术专题文档总览

> Sage 各技术专题的深入文档。本目录补充 [`../README.md`](../README.md) 中核心章节（01-14），聚焦质量门禁、可观测性、架构约束等横切关注点。

---

## 章节目录

| 编号 | 标题 | 一句话简介 |
|---|---|---|
| 15 | [质量门禁](./15-quality-gates.md) | CI / pre-commit / pre-push / 工具链版本与质量阈值 |
| 16 | [可观测性](./16-observability.md) | OpenTelemetry tracer / Prometheus 9 指标 / 审计 jsonl |
| 17 | [前端质量](./17-frontend-quality.md) | FSD 架构 / 测试覆盖 / a11y 状态 |
| 18 | [六边形架构](./18-hexagonal.md) | 五层职责 / 6 个 Protocol / 双轨策略 / import-linter 约束 |
| 19 | [ghm 外部计算集成](./19-ghm-integration.md) | LLM 工具调用桥接 ghm CLI / ExecutableResolver / HTTP 升级预留 |

---

## 与核心章节的关系

| 关注层 | 文档 |
|---|---|
| 用户价值层 | [01 概述](../01-overview.md) — [12 实施计划](../12-plan.md) |
| 横切关注点 | 本目录（15-19） |

---

_本目录文档命名规则：`XX-topic-name.md`（XX 为两位数字，topic-name 为 kebab-case）。_
