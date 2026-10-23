# 91 — 脚注 Phase A：{{fn:}} 内联脚注（Round 57）

> 日期: 2026-09-19 · 分支: `feat/word-footnotes`
> 系列: Word/Office 写作能力增强第 58 轮（按 90 号设计评审稿 Phase A）

## 1. 定位

学术论文脚注支持的最小闭环：正文段落写 `{{fn:备注文本}}`，生成时解析
为 `w:footnoteReference` run（id 按出现顺序 1..N），备注文本挂载进
`word/footnotes.xml` part（含 id=-1/0 系统脚注）。

## 2. 变更

- `_split_cross_ref_segments` 扩展 `fn` 分支（footnotes 累积表入参，
  与 R46 交叉引用拆段同机制）；`_write_cross_ref_segment` 增 fnref
  分支（`w:footnoteReference` run）；
- `_mount_footnotes_part`：OPC 层挂载（Part + PackURI + relate_to
  RELATIONSHIP_TYPE.FOOTNOTES）；文本经 saxutils.escape；
- `read_docx` 增 `footnotes: List[str]`（`_extract_footnotes` 从 part
  回读，跳过系统脚注）；无脚注文档不挂载 part（零变化）。
- 契约：schema content 描述补 `{{fn:}}`；types.ts 读结果加
  `footnotes?: string[]`。

## 3. Win7 对齐与测试

新功能不 cherry-pick 到 release/win7；零新增依赖。
`test_word_footnotes.py` 3 项：part 挂载 + 引用 run + 回读清单、
多脚注顺序编号、无脚注零变化。
