# 分节页码格式与起始号（w:pgNumType）Round 53 实施计划

> 日期: 2026-09-18 · 分支: `feat/pgnum-format` · 基于 main @ 8397c2ec
> 系列: Word/Office 写作能力增强第 54 轮
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 依赖: 零新增。

## 背景

论文/正式报告的页码惯例：前置部分（封面/目录）用罗马数字（i/ii 或
I/II），正文从阿拉伯数字 1 重新起算。当前页脚 PAGE 域只能渲染默认
decimal 格式且全程连续——缺 `w:pgNumType`（fmt/start）支持。

## 批次任务

### A. 模型与布局

- `WordPageSetupSpec` 增 `page_number_format`（decimal/upperRoman/
  lowerRoman/upperLetter/lowerLetter）与 `page_number_start`（ge=0）；
- `_apply_page_setup_to_section`：写/改该节 `w:sectPr/w:pgNumType` 的
  `w:fmt`/`w:start`；两者都未指定时零触碰（既有产物零变化）。主节
  （format_spec.page）与分节新节（section_breaks.page_setup）同一路径
  自动生效；页脚 PAGE 域按 Word 语义自动跟随节格式。

### B. lint 对偶

- `page/numbering` 规则：spec.page 声明了 fmt/start 时校验首节
  pgNumType 实际值，缺失/不符报 error（page 规则语境启用）。

### C. 契约与文档

- schema format_spec.page 增两属性；types.ts WordPageSetupSpec 同步；
- paper-writing/report-writing SKILL 补"目录罗马页码、正文阿拉伯从 1"
  组合示例；技术文档 89 号、CHANGELOG。

## 验证

- 新测试：主节 pgNumType 写入、分节各自 fmt/start、lint 检出；
  word 家族回归 + ruff。

## Round 54 候选

- Word COM 前端徽章细分（需前端协调）
- 脚注/尾注（footnotes.xml part，工程量大需先设计）
