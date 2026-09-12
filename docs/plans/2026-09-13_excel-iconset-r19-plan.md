# Excel 图标集条件格式 Round 19 实施计划（icon_set 规则补全 R17 三件套之外的第 4 类）

> 日期: 2026-09-13 · 分支: `feat/excel-iconset-rule` · 基于 main @ 9ee9d49d
> 系列: Word/Office 写作能力增强第 11 轮（R17 条件格式 #703 / R18 下拉验证
> #706 延伸）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 零新增依赖（openpyxl IconSetRule 原生能力，已在本机验证 2.35 兼容 openpyxl
> 3.1 的 IconSetRule(icon_style=…) 用法）。

## 背景（Round 18 合并后再分析）

R17 条件格式三件套（数据条/色阶/重复值）之后，状态类列（进度/风险等级）
更常用**图标集**（↑→↓ 箭头、红黄绿灯）。openpyxl `IconSetRule` 原生支持
`'3Arrows'/'3TrafficLights1'/'4RedToBlack'/'5Rating'` 等样式。本轮把
`icon_set` 补为第 4 种 `rule_type`，复用 R17 全部管线。

## 批次任务

### A. 模型扩展（`ExcelConditionalFormatSpec`）

- `rule_type` 枚举加 `"icon_set"`
- 新增 `icon_style`: Literal["3Arrows","3TrafficLights1","3Signs",
  "3Symbols","4Arrows","4RedToBlack","4Rating","5Arrows","5Rating"]
  （默认 "3Arrows"，仅 icon_set 用）
- 图标阈值固定按百分比三/四/五等分（openpyxl values=[0..100]），不暴露
  阈值配置（YAGNI，复杂阈值场景后续再加）

### B. 生成器（`_apply_conditional_formats` 加 icon_set 分支）

`IconSetRule(icon_style=…, type='percent', values=[等分点])`；icon_style
非法值模型层 Literal 拒绝。

### C. 工具 schema + 前端契约同步（enum 加 icon_set + icon_style 字段）

### D. 测试（追加到 `test_office_excel_condfmt.py`）

- icon_set 回读（type=="iconSet"、style 断言）
- icon_style 非法值模型拒绝
- 无 icon_set 时零变化（既有用例覆盖）

## Round 20 候选

- journal 接入引用引擎 / TOC 更新收尾 / Pillow（维持不变）
