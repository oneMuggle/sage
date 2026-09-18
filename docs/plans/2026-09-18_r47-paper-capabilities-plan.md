# 论文场景能力可发现化收口（paper-writing + 用户手册）Round 47 实施计划

> 日期: 2026-09-18 · 分支: `docs/paper-capabilities-r47` · 基于 main @ f3b42d1e
> 系列: Word/Office 写作能力增强第 48 轮（纯文档小轮，零代码/依赖）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。

## 背景

R39-R46 的能力（目录真页码、图表目录、交叉引用占位符）只进了
report-writing 技能与技术文档——**paper-writing（论文场景）才是这些
能力的最大受益方**，却零覆盖（连 R13 的 `toc` 都没提）；用户手册
09-office.md 的目录描述还停在"Word 打开后更新域生成"的旧语义。

## 批次任务

### A. paper-writing/SKILL.md

- frontmatter：compatibility 提及目录/图表目录/交叉引用工具面；
  allowed-tools 补 office_refresh_toc。
- 第 4 步 JSON 示例加 `"toc": {}`；要点补"生成时带 refresh_toc: true
  一步到位真页码"。
- 第 2 步起草补交叉引用占位符写法（{{fig:}}/{{tbl:}}，不手编 N）。
- 版式补充能力节补三条：目录与真页码、图表目录、交叉引用域。

### B. docs/user-manual/09-office.md

- 9.2.x 格式能力：目录描述更新为"打开即有目录骨架；生成时带刷新或
  事后让 Sage 刷新得真页码；无 Word 环境 Ctrl+A → F9"。
- 9.2.4 图表与图片：补插图清单/表格清单与交叉引用占位符说明。

### C. 契约测试

- test_shipped_writing_skills.py：paper-writing 正文断言补
  `figure_index`（图表目录）与 `{{fig:`（交叉引用占位符）可发现化。

### D. 账目

- 计划文档 + CHANGELOG（纯文档轮，无技术文档——能力本体已在 76-83 号
  文档记录）。

## 验证

- shipped 技能测试（含新断言）+ ruff 防御性确认。

## Round 48 候选

- Word COM 前端徽章细分（需前端协调）
- 期刊双栏模板（需与 journal 维护方协调）
