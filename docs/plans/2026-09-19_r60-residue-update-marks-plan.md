# residue 补全 + append_paragraphs 交叉引用 Round 60 实施计划

> 日期: 2026-09-19 · 分支: `fix/residue-and-update-marks` · 基于 main @ b9e0a8fa
> 系列: Word/Office 写作能力增强第 61 轮
> Win7 对齐: **新功能/测试修复，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 依赖: 零新增。

## 背景

两处收口缺口：① lint 的 `cross_ref/residue` 正则只覆盖 `{{fig:}}/{{tbl:}}`
——R57/R59 引入的 `{{fn:}}/{{en:}}` 残渍不告警；② office_update 的
`append_paragraphs` op 写入的文本不解析交叉引用占位符——追段落引用
"如图 N 所示"只能手编（或留下残渍触发 residue）。

## 批次任务

### A. residue 正则补全（word_lint）

`_CROSS_REF_RESIDUE_RE` 扩为 `(fig|tbl|fn|en)`，测试补 en 残渍检出。

### B. append_paragraphs 支持 {{fig:}}/{{tbl:}}（edit.py）

- `_collect_caption_bookmarks(doc)`：域外扫描 SEQ 题注段
  （图N/表N + 文本），构建 文本 → (书签名, 缓存显示) 映射
  （生成期书签 `_RefFig{n}`/`_RefTbl{n}` 在 R46 起随题注写入）；
- append_paragraphs：全部 spec 预校验占位符可解析（all-or-nothing，
  与其余 op 的失败语义一致）后，分段写入（text run + REF 复杂域，
  复用 `word_layout.append_ref_field`）；
- {{fn:}}/{{en:}} 追加需 part 追加语义（已存在 part 的编号续接），
  本轮不支持——残渍由 residue lint 提示，规划 Phase 后续。

### C. 测试与账目

- en 残渍检出；append_paragraphs 解析 REF 域 + 未知题注 all-or-nothing
  拒绝且零写入；技术文档 94 号、CHANGELOG。

## 验证

- edit/word_lint 家族回归 + ruff。

## Round 61 候选

- append_paragraphs 支持 {{fn:}}/{{en:}}（part 追加语义）
- Word COM 前端徽章细分（需前端协调）
