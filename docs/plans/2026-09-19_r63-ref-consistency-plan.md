# lint 补脚注/尾注引用一致性 Round 63 实施计划（小轮）

> 日期: 2026-09-19 · 分支: `fix/ref-consistency-lint` · 基于 main @ d5ab6b9d
> 系列: Word/Office 写作能力增强第 64 轮
> Win7 对齐: 纯校验层变更；不涉回流。依赖: 零新增。

## 背景

R57（脚注）/R59（尾注）的引用 run（`footnoteReference`/`endnoteReference`）
指向 part 中的 note id。手工改动或外部工具生成的文档可能出现"引用 id
无对应 note"的损坏态——Word 打开时报"内容有问题"，用户难以定位。
lint 补一致性校验。

## 批次任务

- `word_lint`：`_check_ref_consistency`——扫描正文
  footnote/endnoteReference 的 id，对照 footnotes/endnotes part 的
  真实 note id 集合（跳过系统脚注），缺失 → `footnote/broken_ref` /
  `endnote/broken_ref` error；无引用的文档零开销跳过。
- 测试：一致文档零违规（R57 生成物）；人为破坏（删 note 留引用）检出。
- 技术文档 96 号、CHANGELOG。

## 验证

- lint 家族回归 + ruff。

## Round 64 候选

- Word COM 前端徽章细分（需前端协调）
- 期刊双栏模板（需与 journal 维护方协调）
