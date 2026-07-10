# 想法：wiki 流式接入后更新 25-llm-wiki-integration.md

> 状态：🎯 Next Up（PR-3 merge 后立即做）
> 日期：2026-07-10
> 关联：
> - Plan: `docs/superpowers/plans/2026-07-08-wiki-streaming.md` §9 step 2 (line 1943)
> - 模板参考: `docs/technical/23-chat-streaming.md`

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
3. 结构对齐 `