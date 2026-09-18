# Excel core properties 对称支持 Round 50 实施计划

> 日期: 2026-09-18 · 分支: `feat/excel-core-metadata` · 基于 main @ 6495f3d3
> 系列: Word/Office 写作能力增强第 51 轮（R49 的 Excel 对称轮）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 依赖: 零新增。

## 背景

R49 给 Word 补了 core properties；Excel 侧（台账/预算归档同样要求
文档属性）保持对称——openpyxl `wb.properties`（creator/subject/
keywords/category/description）。

## 批次任务

### A. 模型与生成器

- `OfficeExcelGenerateRequest.metadata: Optional[ExcelMetadataSpec]`
  （`ExcelMetadataSpec = WordMetadataSpec` 别名——字段本就是文档通用
  的；author→creator、comments→description 的映射在生成器内完成）；
- `generate_xlsx`：仅显式传入才写（与 Word 同口径，不臆造作者）。

### B. 契约

- schema content 描述与 properties：metadata 描述扩为 word/excel 通用；
- types.ts：`OfficeExcelGenerateRequest.metadata?`；
- paper-writing SKILL 数据表附表节补一句。

### C. 测试与账目

- generate_xlsx metadata 回读（creator/subject/keywords/category/
  description）；缺省不写；
- 技术文档 86 号、CHANGELOG。

## 验证

- 新测试 + excel 家族回归 + ruff。

## Round 51 候选

- Word COM 前端徽章细分（需前端协调）
- 阅读侧 read_xlsx/read_docx 暴露 core properties（属性回读）
