# 想法：wiki 流式接入后更新 25-llm-wiki-integration.md

> 状态：🎯 Next Up（PR-3 merge 后立即做）
> 日期：2026-07-10
> 关联：[`docs/superpowers/plans/2026-07-08-wiki-streaming.md`](../../superpowers/plans/2026-07-08-wiki-streaming.md) §9 step 2 (line 1943) · [`docs/technical/23-chat-streaming.md`](../../technical/23-chat-streaming.md)

## 动机

当前 `docs/technical/25-llm-wiki-integration.md` 描述的是 wiki 模块**非流式**的 chat/ingest 行为。但 `2026-07-08-wiki-streaming` 3 PR 全部 merge 后：

- `/api/v1/wiki/chat` 和 `/api/v1/wiki/ingest` 都已切到 NDJSON 流式
- 同步端点已删除（plan §9 明确："sync /chat endpoint is removed"）
- 现有文档会与实际代码行为不符，新人 onboarding 时读文档会困惑

plan §9 已经显式标注：

> "Documentation update: After all 3 PRs land, update `docs/technical/25-llm-wiki-integration.md` to describe the streaming flow (mirror `docs/technical/23-chat-streaming.md` pattern). **Follow-up task, not in this plan.**"

## 想法草图

1. 等 PR-3 (wiki ingest stream) merge 到 main
2. 在 `docs/technical/25-llm-wiki-integration.md` 新增 §"流式架构"章节
3. 结构对齐 [`docs/technical/23-chat-streaming.md`](../../technical/23-chat-streaming.md) 模式（流式架构 + 关键设计 + 测试 + followup 清理）
4. 删除现有描述非流式行为的章节（chat/ingest 旧描述）

## 触发条件 / 何时做

- **必触发**：`release/win7` 的 `2026-07-08-wiki-streaming` 3 PR（PR-1 / PR-2 / PR-3）全部 merge 到 main
- plan §9 已显式标注此为 follow-up task，不属于 streaming 主 PR 范围

## 升级路径

升级到 `docs/superpowers/specs/2026-07-10-update-wiki-integration-docs-design.md` 时：
- 在本文件加 `> 已升级到: specs/2026-07-10-update-wiki-integration-docs-design.md (commit xxx)`
- 重点展开：`§"流式架构"章节的小节结构` · `23-chat-streaming.md 哪些段落值得复用 / 哪些要按 wiki 场景改` · `25-llm-wiki-integration.md Phase 1-8 章节如何处理（保留/折叠/合并）`
- 删除本文件（feature-development.md 约定）

实施后归档到 `docs/technical/25-llm-wiki-integration.md`（原地更新，不是新文件）。

## 风险 / 待澄清

- **PR-3 合并时间不确定**：release/win7 同步周期受 Win7 LTS EOL 影响，触发条件可能推迟
- **文档结构对齐参考过时风险**：`docs/technical/23-chat-streaming.md` 在 win7 sync 后可能新增 § 章节，升级到 specs/ 时需重读最新版
- **Phase 1-8 历史章节去留**：原 25-llm-wiki-integration.md 有 Phase 1-8 大量历史内容，新增 §"流式架构"后整体章节顺序需要重新规划