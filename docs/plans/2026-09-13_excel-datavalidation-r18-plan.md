# Excel 数据验证（下拉列表）Round 18 实施计划

> 日期: 2026-09-13 · 分支: `feat/excel-data-validation` · 基于 main @ 705feb66
> 系列: Word/Office 写作能力增强第 10 轮（R17 条件格式 #703 延伸）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 零新增依赖（openpyxl DataValidation 原生能力）。冲突规避：不触碰
> journal/media 区域。

## 背景（Round 17 合并后再分析）

报告/台账类 xlsx 的"状态/分类"列需要**下拉选项**防止手输错值——
openpyxl 的 `DataValidation(type="list")` 原生支持，模式同 R17。
关键约束：内联列表 `formula1` 为 `'"opt1,opt2,…"'` 形式，**总长 ≤255
字符**（Excel 硬限制），超限时该条跳过（warning）不阻断。

## 批次任务

### A. 模型（`ExcelDataValidationSpec` + `ExcelSheetSpec` 扩展）

`ExcelSheetSpec.data_validations: List[ExcelDataValidationSpec]`（≤20）：
- `range`（A1 记法，同 conditional_formats pattern）
- `options`: 选项列表（1~100 项，每项 ≤50 字符）
- `allow_blank`: bool = True
- `prompt_title` / `prompt`: 可选输入提示（≤60/≤200）

### B. 生成器（`excel.py` 新增 `_apply_data_validations`）

`DataValidation(type="list", formula1='"' + ",".join(options) + '"',
allow_blank=...)`，加 `dv.add(rng)`；选项拼接超 255 字符 → 单条跳过
（warning）；`dv.error/dv.errorTitle` 固定中文报错文案。

### C. 工具 schema（office_create_tool.py）+ 前端契约（types.ts）

sheets items 增补 `data_validations` 数组 schema；types.ts 同步
`ExcelDataValidationSpec`。

### D. 测试（`backend/tests/integration/test_office_excel_datavalidation.py`）

- 下拉规则回读（ws.data_validations.type=="list"、formula1 选项、
  sqref）
- 超 255 字符选项列表跳过不阻断；空 options 模型层拒绝；无规则零变化
- 工具链路端到端

## Round 19 候选

- journal fill_from_content 接入引用引擎（需与 journal 工作流协调）
- TOC 域更新收尾（LibreOffice headless / Word COM 可选通道）
- Pillow 图片管线
