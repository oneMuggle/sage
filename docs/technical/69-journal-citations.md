# 69 — journal 接入引用引擎（Round 21：结构化文献 → 格式化参考文献节）

> 日期: 2026-09-13 · 分支: `feat/journal-citations-r21` · 方案:
> `docs/plans/2026-09-13_journal-citations-r21-plan.md`
> 系列: Word/Office 写作能力增强第 13 轮（R9 引用引擎 #640 与 journal
> 子系统 #584 的打通）

## 1. 定位

R9 引用引擎此前只服务 `generate_docx` 通路。期刊子系统 `fill_from_content`
的参考文献仍是 `JournalContent.references: List[str]` 纯文本拼接——无
编号、无格式保证。本轮把两条通路打通：内容提供**结构化文献**时，复用
R9 引擎按 citation_style 格式化并自动加 `[N]` 编号。

## 2. 变更（纯增量，既有行为零变化）

- `JournalContent` 新增 `structured_references: List[ReferenceSpec]`
  （可选）与 `citation_style`（默认 gbt7714）；
- `_write_sections`：`structured_references` 非空 → 文末"参考文献"段用
  R9 引擎逐条格式化并加 `[N]` 编号；未提供 → 回退 `references` 纯文本
  （既有行为，测试锁定）；
- `ReferenceSpec` 从 `backend.office.models` 引入（office.models →
  journal.models 无循环）。

## 3. Win7 对齐与测试

零新增依赖；不 cherry-pick（31-win7-lts.md §2）；前端 IPC 契约同步
（JournalContent 可选字段）。
`tests/integration/office/journal/test_generator.py` 追加 2 项：结构化
文献格式化断言（含 GB/T 类型码/编号）、纯文本回退零变化。journal 全套
9 项 + ruff/tsc/eslint 全绿。

## 4. 系列状态（R7-R21）与 Round 22 候选

十五轮：Word 侧全闭环 + Excel 格式/条件格式/下拉验证 + journal 引用
打通。Round 22 候选：TOC 域更新收尾（headless/COM）、Pillow 图片管线、
report-writing 技能提及 xlsx 附表能力。
