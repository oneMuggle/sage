# 68 — Excel 图标集条件格式（Round 19：icon_set 第 4 种规则）

> 日期: 2026-09-13 · 分支: `feat/excel-iconset-rule` · 方案:
> `docs/plans/2026-09-13_excel-iconset-r19-plan.md`
> 系列: Word/Office 写作能力增强第 11 轮（R17 条件格式 #703 延伸）

## 1. 变更

`ExcelConditionalFormatSpec.rule_type` 新增第 4 种 **`icon_set`**（进度/
风险等级列的 ↑→↓ 箭头、红黄绿灯），`icon_style` 支持 9 种 openpyxl
图标样式（3Arrows/3TrafficLights1/3Signs/3Symbols/4Arrows/4RedToBlack/
4Rating/5Arrows/5Rating，默认 3Arrows），非法值模型层 Literal 拒绝。

阈值策略：按图标数百分比**等分**（3 图标 → [0,33,67]，5 图标 →
[0,20,40,60,80]）——复杂自定义阈值刻意不暴露（YAGNI，后续按需加）。
复用 R17 全部管线（`_apply_conditional_formats` 加 icon_set 分支、非法
range 单条跳过不阻断）。

## 2. Win7 对齐与测试

零新增依赖；不 cherry-pick（31-win7-lts.md §2）。
追加 3 项测试（icon_set 回读 type=="iconSet"、非法 icon_style 模型拒绝、
默认样式断言）至 `test_office_excel_condfmt.py`（共 10 项全绿）。
工具 schema + 前端 IPC 契约同步。

## 5. Round 20 候选

journal 接入引用引擎、TOC 域更新收尾、Pillow 图片管线。
