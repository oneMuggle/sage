# 65 — Excel 条件格式（Round 17：数据条/色阶/重复值高亮）

> 日期: 2026-09-13 · 分支: `feat/excel-conditional-format` · 方案:
> `docs/plans/2026-09-12_excel-condfmt-r17-plan.md`
> 系列: Word/Office 写作能力增强第 9 轮（R14 Excel 格式增强 #683 延伸）

## 1. 定位

R14 补齐 xlsx 静态格式后，数据可视化 highlight 仍缺：预算超支、进度
滞后等场景需要数据条/色阶/重复值标记。openpyxl 原生支持，接入成本低。

## 2. 变更

`ExcelSheetSpec.conditional_formats: List[ExcelConditionalFormatSpec]`
（≤50，全部可选缺省零变化）。三种规则（`rule_type`）：

| rule_type | 着色方式 | 参数 |
|---|---|---|
| `data_bar` | DataBarRule（min→max 数据条） | `color`（默认 638EC6） |
| `color_scale` | ColorScaleRule 双色色阶 | `min_color`（F8696B）/`max_color`（63BE7B） |
| `duplicate` | FormulaRule（`COUNTIF(range,首格)>1` + 纯色填充） | `fill_color`（FFFF00） |

公共：`range`（A1 记法，pattern 模型层拒绝非法格式）。生成器
`_apply_conditional_formats`（`_apply_sheet_formats` 之后、图表之前）：
openpyxl 级失败单条跳过（warning）不阻断；模型层已拦非法格式。

## 3. Win7 对齐与测试

零新增依赖；不 cherry-pick（31-win7-lts.md §2）。
`tests/integration/test_office_excel_condfmt.py` 6 项：三种规则回读
（dataBar/colorScale/expression）、非法 range 模型拒绝、openpyxl 级失败
跳过不阻断、无规则零变化、office_create 工具链路。

## 4. 系列状态（R7-R17）与 Round 18 候选

十一轮。Round 18 候选：journal 接入引用引擎、TOC 域更新收尾
（headless/COM）、Pillow 图片管线、Excel 下拉数据验证。
