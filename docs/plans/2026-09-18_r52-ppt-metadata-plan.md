# PPT core properties 三件套对称 Round 52 实施计划

> 日期: 2026-09-18 · 分支: `feat/ppt-core-metadata` · 基于 main @ a61a0de3
> 系列: Word/Office 写作能力增强第 53 轮（R49/R50/R51 属性家族收口）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 依赖: 零新增。

## 背景

R49（Word）/R50（Excel）/R51（读侧）之后，pptx 是三件套最后一个没有
core properties 的格式。python-pptx 的 `prs.core_properties` 属性名
（author/subject/keywords/comments/category）与 python-docx 完全一致。

## 批次任务

### A. 模型与生成器/读取器

- `OfficePptGenerateRequest.metadata: Optional[PptMetadataSpec]`
  （`PptMetadataSpec = WordMetadataSpec` 别名，与 R50 Excel 同款）；
- `OfficePptReadResult.metadata: Optional[WordMetadataSpec] = None`；
- generate：仅显式传入才写；read：全空 None（模板默认如实回读）。

### B. 契约与账目

- schema content 描述 metadata 覆盖三格式；types.ts 两个接口加字段；
- 技术文档 88 号、CHANGELOG。

## 验证

- ppt round-trip 测试 + ppt 家族回归 + ruff。

## Round 53 候选

- Word COM 前端徽章细分（需前端协调）
- 期刊双栏模板（需与 journal 维护方协调）
