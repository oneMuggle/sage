# 87 — 读侧 core properties 回读（Round 51）

> 日期: 2026-09-18 · 分支: `feat/read-core-properties`
> 系列: Word/Office 写作能力增强第 52 轮（R49/R50 属性能力的读侧闭环）

## 1. 定位

R49/R50 让生成器写入 core properties，但 read_docx/read_xlsx 不回读
——Sage 无法回答"这篇文档的作者是谁"。本轮补读侧对称。

## 2. 变更

- `OfficeWordReadResult.metadata` / `OfficeExcelReadResult.metadata`:
  `Optional[WordMetadataSpec]`（复用同一模型；全空为 None）。注意
  WordMetadataSpec 定义位置前移至 OfficeWordReadResult 之前（pydantic
  前向引用在显式 model_rebuild 时即解析）。
- `word.py._read_core_metadata` / `excel.py._read_core_properties_metadata`
  ：读侧映射与写侧对偶（docx: author/subject/keywords/comments/category;
  xlsx: creator/subject/keywords/description/category）；空串视为未设
  （模板默认 author="python-docx"/"openpyxl" 会如实回读）。
- 契约：types.ts 两个读结果接口加 `metadata?`。

## 3. Win7 对齐与测试

新功能不 cherry-pick 到 release/win7；零新增依赖。
`test_read_core_metadata.py` 4 项：docx/xlsx round-trip、无属性返回
None（显式清空模板默认后）。
