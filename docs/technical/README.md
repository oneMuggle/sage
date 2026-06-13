# 技术专题文档总览

> Sage 各技术专题的深入文档。本目录补充 [`../README.md`](../README.md) 中核心章节（01-14），聚焦质量门禁、可观测性、架构约束等横切关注点。

---

## 章节目录

| 编号 | 标题                                                 | 一句话简介                                                                                            |
| ---- | ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| 15   | [质量门禁](./15-quality-gates.md)                    | CI / pre-commit / pre-push / 工具链版本与质量阈值                                                     |
| 16   | [可观测性](./16-observability.md)                    | OpenTelemetry tracer / Prometheus 9 指标 / 审计 jsonl                                                 |
| 17   | [前端质量](./17-frontend-quality.md)                 | FSD 架构 / 测试覆盖 / a11y 状态                                                                       |
| 18   | [六边形架构](./18-hexagonal.md)                      | 五层职责 / 6 个 Protocol / 双轨策略 / import-linter 约束                                              |
| 19   | [ghm 外部计算集成](./19-ghm-integration.md)          | LLM 工具调用桥接 ghm CLI / ExecutableResolver / HTTP 升级预留                                         |
| 20   | [Electron 21 桌面壳](./20-electron.md)               | Tauri → Electron 21 迁移理由 / 7 个 Win7 启动开关 / CI 流水线 / Phase 5 真机烟测 SOP                  |
| 21   | [Win7 LTS 维护](./21-win7-lts.md)                    | 18 个月归档时间表 / Win7 用户 Web 化迁移 / 真机烟测 SOP / 风险声明                                    |
| 22   | [LLM 代理路由](./22-llm-proxy.md)                    | `/api/v1/llm/*` 透传上游,绕开浏览器到 Ollama/OpenAI 的 CORS 拦截                                      |
| 23   | [Agents CRUD 端到端](./23-agents-crud.md)            | list/update/toggle 三层链路 (后端路由 → Electron IPC → 前端 API → UI)                                 |
| 24   | [Chat 流式响应端到端](./24-chat-streaming.md)        | NDJSON 协议 + Electron IPC event 桥接 + NDJSON relay + chatStream 中间态文案                          |
| 25   | [Skills 系统端到端](./25-skills-system.md)           | InprocSkillAdapter + 3 路由 + 3 Electron IPC 命令 + 4 builtin skills 端到端可见 (list/toggle/execute) |
| 26   | [LLM Wiki 集成 (PR-8)](./26-llm-wiki-integration.md) | 4 LLM provider 抽象 + prompt 模板 + LanceDB RAG + 知识图谱 8 阶段实施                                 |

---

## 与核心章节的关系

| 关注层     | 文档                                                        |
| ---------- | ----------------------------------------------------------- |
| 用户价值层 | [01 概述](../01-overview.md) — [12 实施计划](../12-plan.md) |
| 横切关注点 | 本目录（15-21）                                             |

---

_本目录文档命名规则：`XX-topic-name.md`（XX 为两位数字，topic-name 为 kebab-case）。_
