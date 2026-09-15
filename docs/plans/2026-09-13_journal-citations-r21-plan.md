# journal 接入引用引擎 Round 21 实施计划（结构化文献 → 格式化参考文献节）

> 日期: 2026-09-13 · 分支: `feat/journal-citations-r21` · 基于 main @ 90d070c5
> 系列: Word/Office 写作能力增强第 13 轮
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 零新增依赖。

## 背景（Round 20 合并后再分析）

R9 建成的引用引擎（`references.py`：ReferenceSpec + GB/T 7714-2015/APA
确定性格式化）此前只接入 `generate_docx` 通路。期刊子系统（#584）的
`fill_from_content` 写参考文献时用 `JournalContent.references: List[str]`
纯文本拼接——无编号、无格式保证。本轮把两条通路打通：journal 内容提供
**结构化文献**时，复用 R9 引擎格式化生成带 `[N]` 编号的参考文献段。

## 批次任务

### A. 模型（journal/models.py）

- `JournalContent.structured_references: Optional[List[ReferenceSpec]]`
  （R9 引擎的条目模型；None = 不启用）
- `JournalContent.citation_style: Literal["gbt7714","apa"] = "gbt7714"`

### B. 生成器（journal/generator.py）

`_render_references(content)`：structured_references 非空 →
`[i] format_reference(r, style)` 逐条；否则回退 `content.references`
纯文本（既有行为零变化）。fill 写"参考文献"段时优先取渲染结果。

### C. 测试

- `tests/integration/office/journal/test_generator.py` 追加：结构化文献
  生成 `[1] 李四. 题名[J]. …` 格式；无 structured_references 时回退
  references 纯文本
- 既有 journal 测试零回归

## Round 22 候选

- TOC 域更新收尾（headless/COM）
- Pillow 图片管线 / Excel 打印设置
