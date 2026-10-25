# lint 面补强：index 域在位校验 + schema 子集白名单 Round 44 实施计划

> 日期: 2026-09-18 · 分支: `feat/lint-index-fields` · 基于 main @ b8d0010d
> 系列: Word/Office 写作能力增强第 45 轮（R42 图目录/表目录的校验闭环）
> Win7 对齐: 纯校验层变更，零生成行为变化；不涉回流。

## 背景

R42 交付 figure_index/table_index 后，lint（R10）尚不校验这两个声明——
用户拿旧文档按带 index 的 spec 校验时，缺失的目录域不会被发现。同时
TOF 的 instr 同含 "TOC" 前缀，R42 起目录域在位检测存在误满足风险。

## 批次任务

### A. word_lint.py

- `_document_has_field_with_instr(doc, token)` 通用化（fldSimple /
  fldChar 双载体）；
- `_document_has_toc_field` 加 `\c` 排除（TOF 不冒充 TOC）；
- 新规则 `figure_index/presence` / `table_index/presence`。

### B. lint schema 白名单 + 对偶门禁

- office_lint_tool schema 补 toc / figure_index / table_index 声明；
- 契约测试扩展：lint schema 属性 == 声明的可检查子集
  （`LINT_CHECKABLE_SPEC`，section_breaks/first_page_* 无规则有意不列）
  且 ⊆ 模型字段。

### C. 测试与账目

- `test_office_word_lint.py` +3：同 spec 零违规、缺失检出、TOF 不冒充
  TOC；技术文档 81 号、README 索引、CHANGELOG。

## 验证

- lint 全家族回归 + 契约测试 + ruff。

## Round 45 候选

- Word COM 前端徽章细分（需前端协调）
- 交叉引用（"如图N"与题注联动，工程量大需先设计）
