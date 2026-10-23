# 93 — 尾注 endnotes（Phase C，Round 59）

> 日期: 2026-09-19 · 分支: `feat/word-endnotes`
> 系列: Word/Office 写作能力增强第 60 轮（90/91/92 脚注家族的对称收口）

## 1. 定位

尾注（文末集中列出）与脚注结构同构：`word/endnotes.xml` part
（content-type 与 relationship type 均为 endnotes 变体）、
`w:endnoteReference` 引用 run、`w:endnoteRef` 内容标记、
EndnoteText/EndnoteReference 样式。镜像 R57/R58 实现。

## 2. 变更

- `_split_cross_ref_segments` 扩展 `en` 分支（endnotes 累积表入参）；
  `_write_cross_ref_segment` 增 endref 分支；
- `_mount_endnotes_part`（Part + PackURI + relate_to
  RELATIONSHIP_TYPE.ENDNOTES）+ `_ensure_endnote_styles`（幂等）；
- `read_docx` 增 `endnotes: List[str]`（`_extract_endnotes`）；
- 契约：schema content 描述补 `{{en:}}`；types.ts 读结果加
  `endnotes?: string[]`；SKILL 补脚注/尾注选型（随文查阅选脚注，
  集中查阅选尾注）。

## 3. Win7 对齐与测试

新功能不 cherry-pick 到 release/win7；零新增依赖。
`test_word_endnotes.py` 3 项：part 挂载 + 引用 run + 样式注入 +
回读、脚注尾注同段混用（各自独立 part 与编号）、无尾注零变化。
