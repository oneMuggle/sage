# 脚注 Phase B（样式注入 + 每节重编）Round 58 实施计划

> 日期: 2026-09-19 · 分支: `feat/footnote-phase-b` · 基于 main @ f1ee2a64
> 系列: Word/Office 写作能力增强第 59 轮（91 号 Phase A 的续作）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 依赖: 零新增。

## 背景

Phase A（R57 #1204）的脚注引用 run 引用了 FootnoteReference/FootnoteText
样式，但生成的文档 styles.xml 里没有这两个样式定义——Word 回退默认
渲染（脚注文本不缩小、引用不上标）。Phase B 补：

1. **样式注入**：挂载 footnotes part 时向 styles.xml 注入
   - `FootnoteText` 段落样式（10pt，衔接 Normal）；
   - `FootnoteReference` 字符样式（上标）；
   幂等（已存在则跳过），重复调用安全。
2. **每节重编开关**：`WordPageSetupSpec.footnote_restart_each_section
   : bool`——该节 sectPr 写 `w:footnotePr/w:numRestart w:val="eachSect"`
   （分节后脚注编号每节从 1 重排；默认 continuous 零触碰）。

## 验证

- 样式注入幂等 + 两样式存在；footnotePr 写入与未声明零触碰；
  Phase A 家族回归 + ruff。技术文档 92 号、CHANGELOG。

## Round 59 候选

- office_update 通路支持 {{fn:}}（edit ops 解析）
- Word COM 前端徽章细分（需前端协调）
