# 80 — office_create schema 漂移卫生修复（Round 43）

> 日期: 2026-09-18 · 分支: `fix/office-schema-drift`
> 系列: Word/Office 写作能力增强第 44 轮（纯卫生小轮，零行为变更）

## 1. 定位

R42 实施中发现：`office_create` 的 LLM 工具 schema（format_spec 属性）
缺 `toc`（R13 交付）与 `section_breaks`（R26 交付）——能力在引擎模型
与生成器里存在，但 **schema 未声明即对 LLM 不可见，等于没做**；
`types.ts` 亦缺 `section_breaks`（WordSectionBreakSpec 接口从未建）。
根因：模型字段 → 工具 schema / TS 契约的同步靠人肉，无门禁。

## 2. 变更

- `office_create` schema：format_spec 补 `toc`（heading_text / levels /
  placeholder_text）与 `section_breaks`（start_paragraph + page_setup
  数组）声明——目录域与分节横排能力对 LLM 可发现化。
- `types.ts`：新增 `WordSectionBreakSpec` 接口 +
  `WordFormatSpec.section_breaks?` 字段。
- **防漂移门禁** `test_office_create_schema_contract.py`：
  1. 运行时自省——工具 schema 的 format_spec 属性集合 **全等**
     `WordFormatSpec.model_fields`（引擎加字段不带 schema 声明即红）；
  2. types.ts 文本自省——`export interface WordFormatSpec` 块键覆盖
     模型全部字段（前后端契约不再单侧漂移）。

## 3. Win7 对齐与测试

纯 schema 声明 + 测试，零 Python 行为变更；不涉回流。
255 passed（tools 全量 + 图表目录 + 技能）+ ruff 全绿。
