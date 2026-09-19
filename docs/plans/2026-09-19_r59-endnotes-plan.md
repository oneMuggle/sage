# 尾注 endnotes（Phase C）Round 59 实施计划

> 日期: 2026-09-19 · 分支: `feat/word-endnotes` · 基于 main @ e014497e
> 系列: Word/Office 写作能力增强第 60 轮（90/91/92 号脚注家族的对称收口）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 依赖: 零新增。

## 背景

90 号设计稿 Phase C：尾注（endnotes，文末集中列出）与脚注结构同构——
`endnotes.xml` part（relationship type `.../endnotes`，content-type
`...endnotes+xml`）、`w:endnoteReference` 引用 run、`w:endnoteRef`
内容标记、样式 EndnoteText/EndnoteReference。镜像 R57/R58 实现。

## 批次任务

### A. 生成与挂载（word.py）

- `{{en:备注文本}}` 内联标记 → `w:endnoteReference` run（id 按出现
  顺序 1..N），备注文本挂载 `word/endnotes.xml` part（系统尾注
  id=-1/0 同构；relationship `ENDNOTES`）；
- `_split_cross_ref_segments` 扩展 `en` 分支 + `_write_cross_ref_segment`
  增 endref 分支；`_mount_endnotes_part` + `_ensure_endnote_styles`
  （EndnoteText/EndnoteReference 样式，幂等同 R58）。

### B. 读侧与契约

- `OfficeWordReadResult.endnotes: List[str]`（`_extract_endnotes`）；
- schema content 描述补 `{{en:}}`；types.ts 读结果加 `endnotes?: string[]`；
- SKILL 补一句（尾注 vs 脚注的选型说明）。

### C. 测试与账目

- round-trip / 多尾注顺序 / 无尾注零变化；技术文档 93 号、CHANGELOG。

## 验证

- 新测试 + word 家族回归 + ruff。

## Round 60 候选

- Word COM 前端徽章细分（需前端协调）
- 脚注/尾注在 office_update 通路的追加支持
