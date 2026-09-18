# report-writing 技能补充打印/表头样式/页边距说明 Round 38 实施计划（纯文档）

> 日期: 2026-09-16 · 分支: `feat/r38-print-docs` · 基于 main @ a6836f38
> 系列: Word/Office 写作能力增强第 39 轮（纯文档小轮，零代码/依赖）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。

## 背景

R23（打印设置 #730）、R28（打印标题行 #814）、R31（页边距 #886）、R36
（表头行样式 #1048）交付后，report-writing 技能的"Excel 附表与打印"节
只覆盖了部分能力。本轮补全：表头行样式（Word 侧）、打印标题行/页边距
的显式说明，并给出一句组合示例（方便 LLM 一次调用满足组合需求）。

## 批次任务

### A. report-writing/SKILL.md

"Excel 附表与打印"节更新：
- 打印设置补全：打印页眉页脚（print_header/print_footer，&P 页码占位）
- 页边距（margins_cm，厘米）
- Word 表格表头行样式（header_style：加粗+浅灰底+居中）
- 组合示例："预算表横向打印、每页带标题行、金额千分位"

### B. paper-writing/SKILL.md

无需变更（论文场景少用 Excel 打印；版式补充能力节已覆盖）。

### C. 验证

- shipped 技能测试全绿（skill_md 装载/激活）
- ruff（无 Python 变更，防御性确认）

## Round 39 候选

- TOC 真页码版（headless/COM）
- Pillow 阈值配置化（per-sheet）
- Word 横排分节+宽表组合场景文档
