# 读侧 core properties 回读 Round 51 实施计划

> 日期: 2026-09-18 · 分支: `feat/read-core-properties` · 基于 main @ a875ca4b
> 系列: Word/Office 写作能力增强第 52 轮（R49/R50 属性能力的读侧闭环）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 依赖: 零新增。

## 背景

R49/R50 让生成器写入 core properties，但 read_docx/read_xlsx 不回读
——Sage 无法回答"这篇文档的作者是谁"。

## 批次任务

### A. 模型与读取器

- `OfficeWordReadResult.metadata` / `OfficeExcelReadResult.metadata`:
  `Optional[WordMetadataSpec]`（复用同一模型；全空 None）。
  WordMetadataSpec 定义前移（pydantic 前向引用在显式 model_rebuild 时
  即解析）。
- `word._read_core_metadata` / `excel._read_core_properties_metadata`：
  读侧映射与写侧对偶（xlsx: creator→author、description→comments）；
  空串视为未设；模板默认（python-docx/openpyxl）如实回读。

### B. 契约与账目

- types.ts 两个读结果接口加 `metadata?`；技术文档 87 号、README 索引、
  CHANGELOG。

## 验证

- round-trip 测试 4 项（docx/xlsx 有无属性两态）+ office 回归 + ruff。

## Round 52 候选

- Word COM 前端徽章细分（需前端协调）
- 期刊双栏模板（需与 journal 维护方协调）
