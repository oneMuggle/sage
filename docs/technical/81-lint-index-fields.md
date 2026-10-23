# 81 — lint 面补强：index 域在位校验 + schema 子集白名单（Round 44）

> 日期: 2026-09-18 · 分支: `feat/lint-index-fields`
> 系列: Word/Office 写作能力增强第 45 轮（R42 图目录/表目录的校验闭环）

## 1. 定位

R42 交付 figure_index/table_index 后，lint（R10）尚不校验这两个声明——
用户拿旧文档按带 index 的 spec 校验时，缺失的目录域不会被发现。本轮：
spec 声明了 index 就校验对应 `TOC \c` 域在位；顺带把 lint 工具 schema
的 format_spec 声明与"有规则的可检查子集"用对偶测试锁死（R43 全等
门禁的 lint 侧姊妹篇——lint 是有意子集，白名单化而非全等）。

## 2. 变更

- `word_lint.py`：
  - `_document_has_field_with_instr(doc, token)` 通用化（fldSimple /
    fldChar 双载体）；
  - `_document_has_toc_field` 加 `\c` 排除——TOF 的 instr 也含 "TOC"
    前缀，否则 R42 引入 TOF 后 toc/presence 会被误满足；
  - 新规则 `figure_index/presence`、`table_index/presence`：spec 声明
    即要求文档存在 `TOC \c "图"|"表"` 域（字面"图N"文本不算）。
- `office_lint_tool` schema：format_spec 补 toc / figure_index /
  table_index 声明。
- `test_office_create_schema_contract.py`：新增 lint 白名单对偶测试——
  lint schema 属性 == 声明的可检查子集（`LINT_CHECKABLE_SPEC` 常量，
  加规则时同步）且 ⊆ 模型字段（防 schema 虚报）。

## 3. Win7 对齐与测试

纯校验层变更，零生成行为变化；不涉回流。`test_office_word_lint.py`
+3：同 spec 零违规（真图端到端）、缺失检出、TOF 不冒充 TOC（\c 排除
回归）；契约测试 4 项全绿。
