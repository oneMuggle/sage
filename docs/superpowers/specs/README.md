# Sage 设计 Spec 归档

> 本目录收录 Sage 各功能/阶段的**设计 spec**。功能实施后,spec 保留作为"设计 vs 实际"对比基线。

## 目录定位

- **功能**: 设计阶段的取舍/方案讨论
- **状态**: 即使对应功能已实现,spec 不删除
- **可参考价值**: 对比"设计预期"与"实现实际"的偏差,作为未来重构的参考

## 归档策略

| 阶段 | 操作 |
|---|---|
| spec 阶段 | spec 写入本目录,标 `状态: 设计中` |
| 实施完成 | spec 状态改为 `状态: 已实施`,**保留在本目录** |
| 实施内容并入 docs/ | spec 仍保留;同时新章节并入 `docs/technical/` 或 `docs/user-manual/` 主目录 |

## 章节目录

| 日期 | 标题 | 一句话简介 |
|---|---|---|
| 2026-06-04 | [LLM Pipeline Tool System Design](./2026-06-04-llm-pipeline-tool-system-design.md) | Sage LLM 链路打通 + 工具系统设计 |
| 2026-06-05 | [Sage 质量优化 Design](./2026-06-05-sage-quality-optimization-design.md) | Sage 全栈质量优化设计 |
| 2026-06-22 | [localStorage → Backend Design](./2026-06-22-localstorage-to-backend-design.md) | localStorage 配置存储迁移至后端 SQLite 设计 |
| 2026-06-23 | [Win7 LTS Release Workflow Design](./2026-06-23-win7-lts-release-workflow-design.md) | 双轨 release 工作流（main → Win10+ & release/win7 → Win7 LTS） |
| 2026-06-25 | [aionui-inspired UI Design](./2026-06-25-aionui-inspired-ui-design.md) | Sage AionUi 借鉴方案 — 设计文档 |
| 2026-06-27 | [LLM Wiki Folder Picker Design](./2026-06-27-llm-wiki-folder-picker-design.md) | LLM Wiki 项目创建/打开：原生文件夹选择器 |
| 2026-06-29 | [agentskills.io Spec Conformance Design](./2026-06-29-agentskills-io-spec-conformance-design.md) | AgentSkills.io Spec Conformance Design |
| 2026-06-30 | [Skills Management Delete/Hot-Reload Design](./2026-06-30-skills-management-delete-hotreload-design.md) | Skills 管理: 删除 + 热重载设计 |
| 2026-07-01 | [Skills Load New Design](./2026-07-01-skills-load-new-design.md) | Skills 加载新技能 — Design Spec |
| 2026-07-02 | [Electron Logging Design](./2026-07-02-electron-logging-design.md) | Electron 桌面日志 — Design Spec |
| 2026-07-06 | [Sage Release Tiers Design](./2026-07-06-sage-release-tiers-design.md) | Sage 版本生命周期分级（alpha → beta → preview → stable） |
| 2026-07-08 | [Wiki Streaming Design](./2026-07-08-wiki-streaming-design.md) | Sage LLM Wiki — 流式聊天/摄取接入设计 |
| 2026-07-10 | [Release Branch Strategy Design](./2026-07-10-release-branch-strategy-design.md) | Sage Release Branch 策略（稳定化分支 + 下游消费镜像） |
| 2026-07-17 | [Docs Cleanup Design](./2026-07-17-docs-cleanup-design.md) | Sage 文档整理 (Docs Cleanup) — 设计 Spec |

## 与其他目录关系

| 目录 | 定位 |
|---|---|
| [`docs/plans/`](../../plans/) | **进行中**的实施计划。功能完成后并入主目录并删除(规则见 `feature-development.md`) |
| [`docs/technical/`](../../technical/) | 已归档的**横切关注点**技术文档 |
| [`docs/user-manual/`](../../user-manual/) | 终端用户操作指南 |
| [`docs/superpowers/ideas/`](../ideas/) | 暂不做的零散想法 |
| [`docs/superpowers/plans/`](../plans/) | 已合并的**历史执行计划**(2026-07-17 整理后已清空,仅保留当前 cleanup 自身) |

> 维护规则来源:`feature-development.md`(项目根)。