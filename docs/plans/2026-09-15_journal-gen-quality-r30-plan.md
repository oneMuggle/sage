# journal generate 结构化文献质量提升 Round 30 实施计划

> 日期: 2026-09-15 · 分支: `feat/journal-gen-quality` · 基于 main @ c36adabf
> 系列: Word/Office 写作能力增强第 21 轮（R25 generate 接入 #768 的质量延伸）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 零新增依赖。冲突规避：不触碰 journal/parser 与 pandoc 通路。

## 背景（Round 29 合并后再分析）

R25 让 `generate_article` 的 LLM prompt 产出 `structured_references`。
当前 `JournalContent.model_validate(last_content)` 对**整包**校验——
LLM 产出的一条次品条目（缺 title / ref_type 拼错 / 字段超长）会让
**整个 content 校验失败**，触发两轮自纠甚至最终抛错；而其余合法条目
本可用。LLM 输出的不确定性决定了逐条清洗才是正确姿态。

## 批次任务

### A. 清洗函数（journal/generator.py）

`sanitize_structured_references(raw) -> Tuple[List[ReferenceSpec], int]`：
- 逐条 `ReferenceSpec.model_validate`；失败条目跳过 + warning（含原始
  条目摘要）；
- `key` 缺失/重复时自动补唯一 key（`ref-N` / `ref-N-2`）；
- 返回（合法条目列表, 剔除数）。

### B. 接入（generate_article）

`JournalContent.model_validate(last_content)` 之前：从 last_content 弹出
`structured_references` 原始列表 → 清洗 → 回填为合法条目。全为次品 →
`structured_references` 置空（回退 references 纯文本通路，R21 语义），
**不阻断生成**。

### C. 测试（test_llm_generator.py 追加）

- 混合好坏条目 → 合法条目保留、次品剔除、生成成功
- 全为次品 → structured_references 为空、生成仍成功（走纯文本回退）
- key 重复自动补唯一

## Round 31 候选

- TOC 真页码版（headless/COM，需求评审后立项）
- Excel 打印扩展（页边距按打印方向联动）
- Pillow 阈值配置化（环境变量）
