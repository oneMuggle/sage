# Word 脚注 Phase A（{{fn:}} 内联脚注 + footnotes part 挂载 + 回读）Round 57 实施计划

> 日期: 2026-09-19 · 分支: `feat/word-footnotes` · 基于 main @ a60586392
> 系列: Word/Office 写作能力增强第 58 轮（按 90 号设计评审稿 Phase A）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 依赖: 零新增（OOXML part 手术用 python-docx 既有 OPC 层）。

## 背景

按 90 号设计稿实现写侧最小闭环：正文段落写 `{{fn:备注文本}}`，生成时
解析为 `w:footnoteReference` run（id 按出现顺序 1..N），备注文本写入
挂载的 `word/footnotes.xml` part；`read_docx` 回读脚注清单。

## 批次任务

### A. footnotes part 挂载（word.py 内 `_mount_footnotes_part`）

- 构造 footnotes.xml：`separator`(-1)/`continuationSeparator`(0) 系统
  脚注 + 真实脚注（`w:footnoteRef` + 空格 + 文本，pStyle
  FootnoteText/rStyle FootnoteReference）；
- `Part(PackURI("/word/footnotes.xml"), content_type, xml, package)` +
  `doc.part.relate_to(part, RELATIONSHIP_TYPE.FOOTNOTES)`；
- 文本经 `xml.sax.saxutils.escape` 转义。

### B. 正文内联解析

- 交叉引用正则扩展 `fn` 分支：`_split_cross_ref_segments` 增
  `("fnref", footnote_id, "")` 段（附 footnotes 累积列表入参）；
- `_write_cross_ref_segment` 增 fnref 分支（写 `w:footnoteReference`
  run）；body 循环后挂载 part（有脚注才挂）；
- 脚注文本同样支持交叉引用占位符？否——保持 v1 简单（脚注文本原样）。

### C. 读侧与契约

- `OfficeWordReadResult.footnotes: List[str]`（read_docx 从 part 回读，
  无 part 为空表）；
- schema content 描述补 `{{fn:}}` 语法；types.ts OfficeWordReadResult
  增 `footnotes?: string[]`；
- 技术文档 91 号、CHANGELOG。

### D. 测试

- 生成含 `{{fn:}}` → part 存在 + read 回读清单 + 正文引用 run；
- 无脚注文档零变化（无 footnotes part）；
- 多脚注编号顺序。

## 验证

- 新测试 + word 家族回归 + ruff。

## Round 58 候选

- 脚注 Phase B（样式注入 + 每节重编 + office_update 追加）
- Word COM 前端徽章细分（需前端协调）
