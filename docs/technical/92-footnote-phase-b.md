# 92 — 脚注 Phase B：样式注入 + 每节重编（Round 58）

> 日期: 2026-09-19 · 分支: `feat/footnote-phase-b`
> 系列: Word/Office 写作能力增强第 59 轮（91 号 Phase A 的续作）

## 1. 定位

Phase A 的脚注引用 run 引用 FootnoteReference/FootnoteText 样式但
styles.xml 无定义——Word 回退默认渲染（脚注不缩小、引用不上标）。
Phase B 注入两样式（幂等）并加节级每节重编开关。

## 2. 变更

- `_ensure_footnote_styles`：向 styles.xml 注入 FootnoteText（10pt
  段落样式，basedOn Normal）与 FootnoteReference（字符样式，
  superscript）；styleId 已存在时跳过；lxml 解析片段后 append。
- `_apply_page_setup_to_section`：`footnote_restart_each_section=True`
  时写该节 `w:sectPr/w:footnotePr/w:numRestart=eachSect`（未声明零
  触碰）。
- 契约：schema format_spec.page 增 footnote_restart_each_section；
  types.ts WordPageSetupSpec 同步。

## 3. Win7 对齐与测试

新功能不 cherry-pick 到 release/win7；零新增依赖。
`test_footnote_phase_b.py` 2 项：样式注入幂等、分节 footnotePr 写入
且主节零触碰。Phase A 家族回归全绿。
