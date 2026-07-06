# 技术专题文档总览

> Sage 各技术专题的深入文档。本目录补充 [`../README.md`](../README.md) 中核心章节（01-14），聚焦质量门禁、可观测性、架构约束等横切关注点。

---

## 章节目录

> Note: chapters 21 (Win7 LTS) and 21 (LLM proxy) share a number on disk — both files are prefixed `21-` for historical reasons. Treated as siblings.

| 编号 | 标题                                                 | 一句话简介                                                                                            |
| ---- | ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| 15   | [质量门禁](./15-quality-gates.md)                    | CI / pre-commit / pre-push / 工具链版本与质量阈值                                                     |
| 16   | [可观测性](./16-observability.md)                    | OpenTelemetry tracer / Prometheus 9 指标 / 审计 jsonl                                                 |
| 17   | [前端质量](./17-frontend-quality.md)                 | FSD 架构 / 测试覆盖 / a11y 状态                                                                       |
| 18   | [六边形架构](./18-hexagonal.md)                      | 五层职责 / 6 个 Protocol / 双轨策略 / import-linter 约束                                              |
| 19   | [ghm 外部计算集成](./19-ghm-integration.md)          | LLM 工具调用桥接 ghm CLI / ExecutableResolver / HTTP 升级预留                                         |
| 20   | [Electron 21 桌面壳](./20-electron.md)               | Tauri → Electron 21 迁移理由 / 7 个 Win7 启动开关 / CI 流水线 / Phase 5 真机烟测 SOP                  |
| 21   | [Win7 LTS 维护](./21-win7-lts.md)                    | 18 个月归档时间表 / Win7 用户 Web 化迁移 / 真机烟测 SOP / 风险声明                                    |
| 21   | [LLM 代理路由](./21-llm-proxy.md)                    | `/api/v1/llm/*` 透传上游,绕开浏览器到 Ollama/OpenAI 的 CORS 拦截                                      |
| 22   | [Agents CRUD 端到端](./22-agents-crud.md)            | list/update/toggle 三层链路 (后端路由 → Electron IPC → 前端 API → UI)                                 |
| 23   | [Chat 流式响应端到端](./23-chat-streaming.md)        | NDJSON 协议 + Electron IPC event 桥接 + NDJSON relay + chatStream 中间态文案                          |
| 24   | [Skills 系统端到端](./24-skills-system.md)           | InprocSkillAdapter + 5 路由 + 4 builtin + SKILL.md v2 (gating/scripts/dispatch/slash command) 端到端可见 |
| 25   | [LLM Wiki 集成 (PR-8)](./25-llm-wiki-integration.md) | 4 LLM provider 抽象 + prompt 模板 + LanceDB RAG + 知识图谱 8 阶段实施                                 |
| 26   | [跨平台打包矩阵](./26-packaging-matrix.md)            | Win7/10/11 NSIS + VCRedist bundling 与 Ubuntu deb 覆盖,用户安装指南                                  |
| 27   | [多 Agent 编排层 (M1 typed 化)](./27-multi-agent-orchestration.md) | 12 条 PolicyEngine 规则 + Report schema v1 + Approval token 8 项校验门（参考 claw-code）               |
| 28   | [SKILL.md Spec Conformance (agentskills.io)](./28-skill-md-spec-conformance.md) | backend/skills/skill_md/ 全规范对齐:license/compatibility/allowed-tools + 长度校验 + 单文件形态             |
| 29   | [Electron 桌面日志](./29-electron-logging.md)         | 三层日志架构 / NDJSON 格式 / 路径与保留策略 / Win7 启动失败排查流程                                       |
| 30   | [Release Tiers（发布档位分级）](./30-release-tiers.md) | 4 档分级 (alpha/beta/RC/stable) + SemVer 预发布段 + Win7 LTS 派生 + 升档脚本与流程                            |

---

## 与核心章节的关系

| 关注层     | 文档                                                        |
| ---------- | ----------------------------------------------------------- |
| 用户价值层 | [01 概述](../01-overview.md) — [12 实施计划](../12-plan.md) |
| 横切关注点 | 本目录（15-26）                                             |

---

_本目录文档命名规则：`XX-topic-name.md`（XX 为两位数字，topic-name 为 kebab-case）。_
