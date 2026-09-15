# 67 — Excel 下拉数据验证（Round 18）

> 日期: 2026-09-13 · 分支: `feat/excel-data-validation` · 方案:
> `docs/plans/2026-09-13_excel-datavalidation-r18-plan.md`
> 系列: Word/Office 写作能力增强第 10 轮（R17 条件格式 #703 延伸）

## 1. 定位

台账/报告类 xlsx 的"状态/分类"列需要**下拉选项**防止手输错值。
openpyxl `DataValidation(type="list")` 原生支持，模式同 R17。

## 2. 变更

`ExcelSheetSpec.data_validations: List[ExcelDataValidationSpec]`（≤20）：
`range`（A1 记法 pattern）/`options`（1~100 项）/`allow_blank`（默认
True）/`prompt_title`/`prompt`。

生成器 `_apply_data_validations`：`DataValidation(type="list",
formula1='"opt1,opt2,…"', allow_blank=…)` + 中文错误文案（"无效输入"）。
**关键约束**：内联列表 formula1 总长 ≤255 字符（Excel 硬限制）——超限
该条跳过（warning）不阻断。`showDropDown=False`（openpyxl 语义取反，
False 才显示下拉箭头——反直觉处已在代码注释）。

## 3. Win7 对齐与测试

零新增依赖；不 cherry-pick（31-win7-lts.md §2）。
`tests/integration/test_office_excel_datavalidation.py` 6 项：规则回读
（type/formula1/sqref/promptTitle）、allow_blank=False、超长选项跳过
（其余正常写入）、空 options 模型拒绝、零变化、工具链路。

## 4. 系列状态（R7-R18）与 Round 19 候选

十二轮。Round 19 候选：journal 接入引用引擎、TOC 域更新收尾
（headless/COM）、Pillow 图片管线、Excel 条件格式扩展（图标集）。
