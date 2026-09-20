# 95 — append_paragraphs 支持 {{fn:}}/{{en:}}（Round 61）

> 日期: 2026-09-19 · 分支: `feat/append-fn-en`
> 系列: Word/Office 写作能力增强第 62 轮（R60 的 update 通路补完）

## 1. 定位

R60 给 append_paragraphs 加了 fig/tbl 交叉引用；fn/en 因 part 追加语义
（已存在 part 的编号续接 + blob 增补）推迟。本轮补齐——update 通路
四类占位符全支持。

## 2. 变更

- `word.py`：`_append_notes`（lxml 解析 part.blob 增补 note 元素后回写
  `part._blob`，编号续接）+ `_append_footnotes`/`_append_endnotes`
  （part 不存在时全量挂载；尾注含样式注入）；
- `edit.py`：`_parse_cross_ref_text` 统一化——fig/tbl 走 caption_map
  （未知抛 KeyError 保持 all-or-nothing），fn/en 内容内联（无失败
  路径），返回 (segments, 新脚注, 新尾注)；append_paragraphs 写段后
  调 `_append_footnotes/_append_endnotes` 落 part。

## 3. Win7 对齐与测试

新功能不 cherry-pick 到 release/win7；零新增依赖。
`test_append_fn_en.py` 3 项：脚注编号续接（id=2）、无尾注文档挂载
endnotes part、fig+fn+en 同段混用各归其位。
