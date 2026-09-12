# Excel 条件格式 Round 17 实施计划（数据条/色阶/重复值高亮）

> 日期: 2026-09-13 · 分支: `feat/excel-conditional-format` · 基于 main @ d7517abe
> 系列: Word/Office 写作能力增强第 9 轮（R14 Excel 格式增强 #683 的直接延伸）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 零新增依赖（openpyxl 既有 conditional_formatting 能力）。
> 冲突规避: 不触碰 journal/media 区域。

## 背景（Round 16 合并后再分析）

R14 给 xlsx 附表补了静态格式（表头/冻结/列宽/数字格式），但**数据可视化
 highlight** 仍缺：预算超支、进度滞后等场景需要数据条/色阶/重复值标记，
目前只能靠 LLM 手写公式说明。openpyxl 原生支持
`DataBarRule / ColorScaleRule / CellIsRule / FormulaRule`，接入成本低。

## 批次任务

### A. 模型（`ExcelConditionalFormatSpec` + `ExcelSheetSpec` 扩展）

`ExcelSheetSpec.conditional_formats: List[ExcelConditionalFormatSpec]`
（≤50；全部可选，缺省零变化）。每种规则二选一：

- `data_bar`: `range`(A1 记法，如 "B2:B100") + `color`(RGB hex，默认
  "638EC6")
- `color_scale`: `range` + `min_color`/`max_color`（默认 F8696B→63BE7B）
- `duplicate`: `range` + `fill_color`（默认 FFFF00，重复值高亮）

公共字段：`sheet`（缺省当前 sheet）不需要——规则挂在本 sheet spec 上。

### B. 生成器（`excel.py` 新增 `_apply_conditional_formats`）

在 `_apply_sheet_formats` 之后调用；每条规则转 openpyxl Rule：
- data_bar → `DataBarRule(start_type='min', end_type='max', color=...)`
- color_scale → `ColorScaleRule(start_type='min', start_color=...,
  end_type='max', end_color=...)`
- duplicate → `FormulaRule(formula=[f'COUNTIF({range},首单元格)>1'],
  fill=PatternFill)`；range 非法（openpyxl 抛异常）→ 单条跳过并
  logger.warning，不阻断生成

### C. 工具 schema（office_create_tool.py）+ 前端契约（types.ts）

sheets items 增补 `conditional_formats` 数组 schema；types.ts 同步
`ExcelConditionalFormatSpec`。

### D. 测试（`backend/tests/integration/test_office_excel_condfmt.py`）

- data_bar/color_scale/duplicate 各自写入后回读
  `ws.conditional_formatting` 断言（类型/range/颜色）
- 非法 range 跳过不阻断；无规则零变化；office_create 工具链路

## Round 18 候选

- journal fill_from_content 接入引用引擎（需与 journal 工作流协调）
- TOC 域更新收尾（LibreOffice headless / Word COM 可选通道）
- Pillow 图片管线
