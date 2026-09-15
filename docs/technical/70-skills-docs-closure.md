# 70 — 写作技能工作流与用户手册收口（Round 24）

> 日期: 2026-09-13 · 分支: `feat/writing-skills-docs-update`
> 系列: Word/Office 写作能力增强第 15 轮（R7-R23 的文档收口轮）

## 1. 定位

R7-R23 建成了 Word 全链路（版式/元素/引用/校验/自愈/目录/读取）与
Excel 家族（格式/条件格式/下拉/打印）+ Pillow 图片管线，但**可发现
入口**没跟上：两个写作技能的工作流没提 Excel 附表/图片管线/打印设置，
用户手册 09-office.md 也未覆盖 R7-R23 的能力。纯文档轮，零代码变更。

## 2. 变更

- `paper-writing/SKILL.md`：新增"数据表附表（可选）"节——office_create
  excel 附表的表头样式/冻结/列宽/数字格式/条件格式/下拉/打印能力清单
- `report-writing/SKILL.md`：新增"Excel 附表与打印（可选）"节 + 图片
  管线说明（>8MB 需 Pillow，未装则 >10MB 拒绝）
- `docs/user-manual/09-office.md`：新增 9.2.1b（Word 版式引擎怎么给
  格式要求——页面/正文/标题/编号/引用/自检）、9.2.1c（Excel 附表格式
  与打印）、9.2.1d（图片自动压缩）三节，面向最终用户话术

## 3. Win7 对齐与验证

纯 Markdown，零代码/依赖变更；不 cherry-pick（31-win7-lts.md §2）。
回归：shipped 技能测试 + 自动激活 + journal + excel 打印共 81 项全绿；
tsc 全绿。

## 4. 系列总览（R7-R24，十七轮）

| 层 | 轮次 | 交付 |
|---|---|---|
| Word 版式 | R7 #622 | FormatSpec 版式引擎（页面/样式/页眉页脚/页码） |
| Word 内容 | R8 #635 | 行内插图+题注、三线表、标题编号 |
| Word 引用 | R9 #640 | GB/T 7714 引擎、文中标记、参考文献表、BibTeX |
| 校验/自愈 | R10 #647 / R12 #665 | 格式 Linter、自动修复 |
| Excel 家族 | R14 #683 / R17 #703 / R18 #706 / R19 #708 / R23 #730 | 表头样式/冻结/列宽/合并、条件格式、下拉、图标集、打印 |
| 读取/入口 | R15 #689 / R16 #694 / R24 | 页眉页脚提取、@摘要版式信息、技能/手册收口 |
| 打通 | R21 #714 | journal fill 接入引用引擎 |
| 图片 | R22 #720 | Pillow 懒加载压缩管线 |

Round 25 候选：TOC 域更新收尾（headless/COM）、Word 横排分节、
Pillow 进 main 通道 requirements（依赖评审后）。
