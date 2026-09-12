# Excel 格式增强 Round 14 实施计划（表头样式/冻结/自适应列宽/数字格式）

> 日期: 2026-09-12 · 分支: `feat/excel-format-enhancements` · 基于 main @ aeae005d
> 系列: Word/Office 写作能力增强第 8 轮——报告写作场景的数据表侧短板
> （R7-R13 已把 Word 侧闭环；预算表/数据表等 xlsx 产物仍是裸样式）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 零新增依赖（openpyxl 既有能力）。冲突规避：excel.py 属我的既有模式区。

## 背景（Round 13 合并后再分析）

`generate_xlsx` 目前产出裸样式：表头无样式（与数据行视觉无别）、无冻结
首行（长表滚动丢失表头语境）、无数字格式（金额/百分比显示为原始值）。
报告写作（report-writing 技能）常产 xlsx 附表（预算/统计），与 Word 侧
的"格式即配置"不对称。本轮给 `ExcelSheetSpec` 补三层格式控制（全部
可选、缺省零变化）。

## 批次任务

### A. 模型扩展（`ExcelSheetSpec`）

- `header_style: bool = False`——表头行加粗 + 浅灰底（D9D9D9）+ 边框
- `freeze_header: bool = False`——冻结 A2（首行表头 + 首列语境）
- `autofit_columns: bool = False`——按内容自适应列宽（openpyxl 无原生
  autofit，按"最大字符宽 × 1.2 + 2"启发式，中文按 2 倍宽度计；上限 60）
- `number_formats: Optional[Dict[str, str]]`——按列名（header 名）映射
  Excel 数字格式串（如 `{"金额": "#,##0.00", "占比": "0.0%"}`），未知
  列名忽略；与 column_widths 显式值互斥（显式列宽优先）

### B. 生成器（`excel.py` 新增 `_apply_sheet_formats`）

在 `_apply_sheet_column_widths` 之后统一应用：表头样式（Font/PatternFill/
Alignment 居中）、freeze_panes、autofit（尊重显式 column_widths）、
数字格式（openpyxl `cell.number_format`，跳过表头与空单元格）。

### C. 工具 schema（`office_create_tool.py`）

excel content 的 sheets items 增补四个字段的 JSON Schema + 中文描述。

### D. 测试（`backend/tests/integration/test_office_excel_formats.py`）

- 旧 payload（无新字段）零变化
- header_style：表头加粗/填充色/居中断言，数据行不受影响
- freeze_header：freeze_panes == "A2"
- autofit：列宽 > 默认、显式 column_widths 优先
- number_formats：目标列格式生效、未知列忽略、公式单元格跳过
- office_create 工具链路端到端

## Round 15 候选

- journal fill_from_content 接入引用引擎（需与 journal 工作流协调）
- TOC 域更新收尾（LibreOffice headless / Word COM 可选通道）
- Excel 条件格式/数据条；Pillow 图片管线
