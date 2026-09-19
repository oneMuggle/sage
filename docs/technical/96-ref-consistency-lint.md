# 96 — 脚注/尾注引用一致性 lint（Round 63）

> 日期: 2026-09-19 · 分支: `fix/ref-consistency-lint`
> 系列: Word/Office 写作能力增强第 64 轮

## 1. 定位

R57/R59 的脚注/尾注引用 run（`footnoteReference`/`endnoteReference`）
指向 part 中的 note id。手工改动或外部工具生成的文档可能出现
"引用 id 无对应 note"的损坏态——Word 打开时报"内容有问题"且难定位。
lint 补一致性校验。

## 2. 变更

- `word_lint._check_ref_consistency`：扫描正文两类引用 run 的 id，
  对照 footnotes/endnotes part 的真实 note id 集合（系统脚注 type 标记
  跳过）；缺失 → `footnote/broken_ref` / `endnote/broken_ref` error。
- `ref_consistency` 无条件入 checked（无引用文档零开销跳过）。

## 3. Win7 对齐与测试

纯校验层变更，不涉回流；零新增依赖。`test_ref_consistency.py` 3 项：
一致文档零违规、人为破坏（改引用 id=2 无对应 note）检出、无引用文档
零开销跳过。
