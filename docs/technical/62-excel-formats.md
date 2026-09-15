# 62 — Excel 格式增强（Round 14：表头样式/冻结/自适应列宽/数字格式）

> 日期: 2026-09-12 · 分支: `feat/excel-format-enhancements` · 方案:
> `docs/plans/2026-09-12_excel-format-r14-plan.md`
> 系列: Word/Office 写作能力增强第 8 轮（R7-R13 见 55-61 号技术文档）

## 1. 定位

R7-R13 把 Word 侧闭环后，报告写作常产的 **xlsx 附表**（预算/统计）仍是
裸样式：表头与数据行视觉无别、长表滚动丢表头、金额/百分比显示原始值。
本轮给 `ExcelSheetSpec` 补四项格式控制，与 Word 侧"格式即配置"对齐。

## 2. 四项能力（全部可选，缺省零变化）

| 字段 | 行为 |
|---|---|
| `header_style` | 表头行加粗 + 浅灰底（D9D9D9）+ 居中（数据行不触碰） |
| `freeze_header` | `freeze_panes = "A2"`（首行冻结） |
| `autofit_columns` | 启发式自适应：按内容最长字符宽（CJK 计 2 倍）× 1.2 + 2，上限 60；**显式 `column_widths` 的列优先不被覆盖** |
| `number_formats` | 按列名映射 Excel 数字格式（`{"金额": "#,##0.00"}`）；未知列名忽略；表头行与公式单元格（`data_type == "f"`）跳过 |

实现：`excel.py` 新增 `_apply_sheet_formats`，在 writer 保存前、
`_apply_sheet_column_widths` 之后调用（autofit 能看到显式列宽）。

## 3. Win7 对齐与测试

零新增依赖（openpyxl 既有能力）；不 cherry-pick（31-win7-lts.md §2）。
`tests/integration/test_office_excel_formats.py` 7 项：旧 payload 零变化
（pandas 表头默认加粗/居中为既有基线）、表头样式/冻结、autofit 宽窄对比
与显式列宽优先、数字格式（未知列忽略/公式跳过）、office_create 工具链路。

## 4. 系列状态（R7-R14）与 Round 15 候选

八轮：Word 侧（版式/元素/引用/校验/技能/自愈/目录）+ Excel 数据表格式。
Round 15 候选：journal 接入引用引擎、TOC 域更新收尾（headless/COM）、
Excel 条件格式/数据条、Pillow 图片管线。
