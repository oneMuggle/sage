# office_create schema 漂移卫生修复 Round 43 实施计划

> 日期: 2026-09-18 · 分支: `fix/office-schema-drift` · 基于 main @ 0940ccf
> 系列: Word/Office 写作能力增强第 44 轮（纯卫生小轮，零行为变更）
> Win7 对齐: 不涉及（工具 schema 是主仓 LLM 面；无 Python 行为变更，
> py38 口径维持）。

## 背景

R42 实施中发现：`office_create` 的 LLM 工具 schema（format_spec 属性）
缺 `toc`（R13 交付）与 `section_breaks`（R26 交付）——能力在引擎与
前端类型里存在，但 LLM 看不见（schema 未声明即不可发现，等于没做）；
`types.ts` 也缺 `section_breaks`（WordSectionBreakSpec 接口从未建）。
根因：模型字段 → 工具 schema / TS 契约的同步靠人肉，无防漂移门禁。

## 批次任务

### A. 补 schema 声明（office_create_tool）

- `format_spec.toc`：对象（heading_text/levels/placeholder_text），
  描述目录域能力（R13/R29）。
- `format_spec.section_breaks`：数组（start_paragraph + page_setup
  {size/orientation/margins_cm}），描述横排分节/宽表场景（R26/R37）。

### B. 补 TS 契约（types.ts）

- 新增 `WordSectionBreakSpec` 接口 + `WordFormatSpec.section_breaks?`。

### C. 防漂移门禁（对偶测试）

- `test_office_create_schema_contract.py`：
  1. 运行时自省——`OfficeCreateTool.schema` 的
     `format_spec.properties` 键集合 **==** `WordFormatSpec.model_fields`
     键集合（今后模型加字段不带 schema 声明即红）；
  2. types.ts 文本自省——`export interface WordFormatSpec` 块内的键
     覆盖模型全部字段（前后端契约不再单侧漂移）。

## 验证

- 新对偶测试 + 既有 create 工具/profiles/office 回归；ruff。

## Round 44 候选

- lint_word 工具 schema 的 format_spec 子集声明对偶检查（读类工具
  有意子集，需白名单化而非全等）
- Word COM 前端徽章细分（需协调）
