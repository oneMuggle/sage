# 88 — PPT core properties 三件套对称（Round 52）

> 日期: 2026-09-18 · 分支: `feat/ppt-core-metadata`
> 系列: Word/Office 写作能力增强第 53 轮（R49/R50/R51 属性家族收口）

## 1. 定位

R49（Word）/R50（Excel）/R51（读侧）之后，pptx 是三件套最后一个没有
core properties 的格式。python-pptx 的 `prs.core_properties` 属性名
（author/subject/keywords/comments/category）与 python-docx 完全一致。

## 2. 变更

- `OfficePptGenerateRequest.metadata: Optional[PptMetadataSpec]`
  （`PptMetadataSpec = WordMetadataSpec` 别名，与 R50 Excel 同款）；
- `OfficePptReadResult.metadata`（全空 None——模板默认
  comments="generated using python-pptx" 如实回读）；
- generate：仅显式传入才写；read：`_read_core_metadata(prs)` 对偶。
- 契约：schema metadata 描述扩为三格式；types.ts 两个接口加字段。

## 3. Win7 对齐与测试

新功能不 cherry-pick 到 release/win7；零新增依赖。
`test_ppt_core_metadata.py` 2 项：round-trip、无属性（显式清空模板
默认后）返回 None。
