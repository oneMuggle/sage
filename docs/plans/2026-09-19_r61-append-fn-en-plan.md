# append_paragraphs 支持 {{fn:}}/{{en:}}（part 追加语义）Round 61 实施计划

> 日期: 2026-09-19 · 分支: `feat/append-fn-en` · 基于 main @ 6a8eba0c
> 系列: Word/Office 写作能力增强第 62 轮（R60 的 update 通路补完）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 依赖: 零新增。

## 背景

R60 给 append_paragraphs 加了 {{fig:}}/{{tbl:}} 交叉引用；{{fn:}}/{{en:}}
因需 part 追加语义（已存在 part 的编号续接 + blob 增补）而推迟。本轮补
齐——update 通路四类占位符全支持。

## 批次任务

### A. word.py 追加 helper

- `_append_footnotes(doc, new_texts)` / `_append_endnotes(doc, new_texts)`：
  - part 不存在 → 走 `_mount_*_part` 全量挂载；
  - 已存在 → lxml 解析 part.blob，按续接编号追加 note 元素（样式引用
    同 Phase A），`part._blob` 回写；
  - 真实脚注起始 id = 现有真实脚注数 + 1（与 R46 书签编号无冲突）。

### B. edit.py append_paragraphs

- `_parse_inline_marks`：统一拆段 fig/tbl（caption_map 解析，未知抛
  KeyError）+ fn/en（内容内联，无失败路径），产出统一段格式
  （text/ref/fnref/endref）；
- 预校验全部 spec 后写入（`word._write_cross_ref_segment` 复用——
  fnref/endref 分支 R57/R59 已备）；写入后 `_append_footnotes/_append_endnotes`
  落 part；all-or-nothing 语义保持。

### C. 测试与账目

- append {{fn:}} → part 增补 + 引用 run + read 回读；{{en:}} 同；
  fig+fn 混用；技术文档 95 号、CHANGELOG。

## 验证

- 新测试 + edit/word 家族回归 + ruff。

## Round 62 候选

- Word COM 前端徽章细分（需前端协调）
- 期刊双栏模板（需与 journal 维护方协调）
