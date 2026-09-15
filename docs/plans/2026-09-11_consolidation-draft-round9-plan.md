# 巡检建议 → 草稿自动生成 Round 9 实施计划（对标 hermes-agent）

> 日期: 2026-09-11 · 分支: `feat/consolidation-auto-draft` · 基于 main @ 5173aac0
> 来源: hermes-agent 对标分析（consolidation review 全闭环）
> Win7 对齐: 全部为**新功能**，不 cherry-pick 到 release/win7（31-win7-lts.md §2）。
> 冲突规避: 避开 p11-embedding / parity-r9 / word-format-spec 在飞区域。

## 背景

Round 5/7 的 LLM 巡检产出 merge/archive/revise **建议**（consolidation_note
台账），止步于"人看建议"。hermes 的 consolidation review 直接到
"修订后内容"。本批把 merge/revise 类建议**自动生成 SkillDraft**
（进既有审批面），打通「巡检 → 建议 → 草稿 → 人工审批 → 落盘 → 台账」
完整闭环；archive 建议仍只提示（已有可逆的 archive 流程，无需草稿）。

安全边界：草稿 status=pending 进既有审批面——**落盘仍需人工批准**，
与 Round 3 审计/回滚设施配合，完全符合「透明可控可回滚」。

## 批次任务

### A. `backend/skills/consolidator.py`

- `async draft_from_suggestion(suggestion, skill_docs) -> Optional[dict]`：
  - merge：LLM 产出合并技能草稿 JSON（新 name / 合并描述 / when_to_use /
    完整 SKILL.md content），宽容解析 + 复用 ReviewService 的 schema 校验
  - revise：LLM 基于原 SKILL.md 全文产出修订稿（同名，仅修订
    description/when_to_use/正文的含糊处）
  - archive：返回 None（无需草稿）
- `async generate_drafts(suggestions, skill_docs, draft_store, provenance)`：
  逐条生成 → `SkillDraft(status=pending, source_context 标
  consolidation 来源 + suggestion 原文)` → draft_store.insert；
  失败单条跳过不中断

### B. 接线

- `legacy_routes.scan_skill_consolidation` 增加 `auto_draft` query 参数
  （默认 true）：建议落台账后生成草稿
- `SkillConsolidationTask`（cron）同样生成草稿（草稿即审批面，安全）

### C. 测试

- `backend/tests/unit/test_consolidation_drafts.py`：merge 草稿生成/
  revise 草稿/archive 跳过/LLM 坏输出单条跳过/草稿入 store pending

## Round 10 候选

- Telegram 审批转发（permission/question 闸口 → 网关消息）
- docker 沙箱执行后端
- hex-legacy 双栈收敛
