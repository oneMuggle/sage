# 73 — journal 结构化文献清洗降级（Round 30）

> 日期: 2026-09-15 · 分支: `feat/journal-gen-quality` · 方案:
> `docs/plans/2026-09-15_journal-gen-quality-r30-plan.md`
> 系列: Word/Office 写作能力增强第 21 轮（R25 generate 接入 #768 的质量延伸）

## 1. 问题

R25 让 `generate_article` 的 LLM 产出 `structured_references`，但
`JournalContent.model_validate` 对**整包**校验——一条次品条目（缺
title / ref_type 拼错）会让整个 content 校验失败，触发两轮自纠仍失败
则最终抛错，而其余合法条目本可用。LLM 输出的不确定性决定了逐条清洗
才是正确姿态。

## 2. 变更

- `_sanitize_structured_references(raw) -> (kept, dropped)`：逐条
  `ReferenceSpec.model_validate`；次品剔除 + `logger.warning`（不阻断）；
  key 冲突自动补唯一后缀（`good1` → `good1-2`）；
- `_sanitize_structured_refs_inplace(content_dict)`：原地清洗 helper
  （供 generate_article 的自纠检查前与最终校验前调用）；
- 全为次品 → 键移除，回退 references 纯文本通路（R21 语义）；
- `generate_structured` 的最终渲染（`_write_sections` R21 分支）不变。

## 3. Win7 对齐与测试

零新增依赖；不 cherry-pick（31-win7-lts.md §2）。
`test_llm_generator.py` 追加 2 项：混合好坏条目（合法保留 + 次品剔除
+ 重复 key 自动改写）、全为次品回退纯文本。journal 全套 9 项全绿。

## 4. Round 31 候选

TOC 真页码版（headless/COM，需求评审后立项）、Excel 打印扩展、
Pillow 阈值配置化。

---

（Round 31 另见 feat-excel-print-margins 分支的打印页边距扩展——
与本文件所述清洗机制相互独立。）
