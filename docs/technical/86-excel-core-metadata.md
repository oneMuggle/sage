# 86 — Excel core properties 对称支持（Round 50）

> 日期: 2026-09-18 · 分支: `feat/excel-core-metadata`
> 系列: Word/Office 写作能力增强第 51 轮（R49 的 Excel 对称轮）

## 1. 定位

R49 给 Word 补了 core properties；Excel 侧（台账/预算归档同样要求
文档属性）保持对称——openpyxl `wb.properties`（creator/subject/
keywords/category/description）。

## 2. 变更

- `OfficeExcelGenerateRequest.metadata: Optional[ExcelMetadataSpec]`
  ——`ExcelMetadataSpec = WordMetadataSpec` 别名（字段本就是文档通用
  的；author→creator、comments→description 的映射是格式差异，模型无
  差异，别名复用避免双份定义漂移）。
- `generate_xlsx`：主流程 `pd.ExcelWriter` 上下文内对 `writer.book`
  应用属性（仅显式传入才写，不臆造作者；空簿兜底分支不涉及）。
- 契约：schema metadata 描述扩为 word/excel 通用；types.ts
  `OfficeExcelGenerateRequest.metadata?`；paper-writing 数据表附表节
  补一句。

## 3. Win7 对齐与测试

新功能不 cherry-pick 到 release/win7（31-win7-lts.md §2）；零新增依赖。
`test_excel_core_metadata.py` 2 项：全字段回读（creator/subject/
keywords/description/category）、缺省不写。excel 家族回归 + ruff 全绿。
