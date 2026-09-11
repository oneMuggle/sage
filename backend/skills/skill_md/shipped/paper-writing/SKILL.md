---
name: paper-writing
description: 撰写期刊论文/学术论文的完整工作流——大纲确认、分章起草、结构化引用（GB/T 7714）、docx 生成与格式自检。当用户要写论文、投稿稿件、毕业论文正文时使用。
license: Apache-2.0
compatibility: 需要 Round 7-10 的 office 工具面（office_create 的 format_spec/references/citations、office_lint_word）
when_to_use: 当用户要撰写期刊论文、学术论文、投稿稿件、毕业论文、课程论文的正文/摘要/参考文献,或用"写论文""帮我写论文""论文投稿""期刊投稿""毕业论文""课程论文""论文大纲""论文初稿"等表达时使用
allowed-tools: write_file office_create office_parse_bibtex office_lint_word ask_user_question
triggers: []
---

# 期刊论文写作

> shipped 基础版。`triggers` 留空——靠 `when_to_use` 语义判断激活；
> 用户可派生自定义版本并自行加触发词。
> 与 builtin WriterSkill 的关系：WriterSkill 产纯文本；本技能走 office
> 工具面产出**格式合规的正式 docx**。

## 触发条件

- "帮我写一篇关于 XX 的论文 / 期刊投稿"
- "把这份研究整理成毕业论文第三章"
- "写论文，格式按学校要求（页边距/字号/行距…）"

## 工作流（五步，不要跳步）

### 1. 大纲确认（必须先问）

用 `ask_user_question` 与用户确认：论文主题、目标章节结构（如 摘要/
引言/方法/实验/结论）、篇幅要求、是否有**单位格式要求**（页边距/字号/
行距/页码/标题样式）。格式要求将映射进 `content.format_spec`——
明确告诉用户"格式由引擎保证，正文不用手写编号"。

### 2. 分章起草（write_file 落盘）

逐章用 `write_file` 把草稿写成 markdown 落盘（如 `<工作区>/paper/01-引言.md`）。
落盘而非直接输出——长文不占上下文，便于用户逐章修订后再汇编。

### 3. 文献准备

- 用户给了 `.bib` 内容/文件 → 先调 `office_parse_bibtex` 解析为
  结构化条目；
- 没有文献文件 → 把用户提供的文献手工整理成 `references` 条目
  （每条必有唯一 `key`，如 `zhang2023`）。
- 引用标记不要手写 `[1]`——在段落 `citations` 里填 key，引擎自动编号。

### 4. 生成 docx（office_create 一次成形）

调 `office_create`（doc_type=word），content 结构：

```json
{
  "title": "论文标题",
  "format_spec": {
    "page": {"size": "A4", "margins_cm": {"top": 2.5, "bottom": 2.5, "left": 3.0, "right": 3.0}},
    "body": {"font_size_pt": 12, "line_spacing": 1.5, "first_line_indent_cm": 0.74},
    "headings": {"h1": {"font_size_pt": 15, "bold": true}},
    "footer": {"page_number": true},
    "numbering": true
  },
  "references": [{"key": "zhang2023", "ref_type": "journal", "title": "...", "authors": ["..."], "year": "2023", "source": "..."}],
  "citation_style": "gbt7714",
  "paragraphs": [
    {"text": "引言", "heading": "h1"},
    {"text": "如文献所述……", "citations": ["zhang2023"]}
  ]
}
```

要点：`format_spec` 只在用户明示格式要求时才细配；参考文献节自动生成，
标题不要写"参考文献"段；标题文本不要手写编号（numbering 引擎生成）。

### 5. 自检与修复（交付前必做）

调 `office_lint_word`（file_path=生成的文档，format_spec 与第 4 步一致），
逐条向用户报告违规与修复建议；可修复项（如编号/题注错位）用重新生成
或 `office_update` 修正后再复检，直到 `ok=true` 或用户接受。

## 不做的事（YAGNI）

- ❌ 不自动下载文献全文（联网检索走 academic-search 技能，人工确认入库）
- ❌ 不预设期刊专用模板（编辑部模板场景走 office_analyze_word_template +
  office_fill_word_template，那是模板填充通路）
- ❌ 不替用户做学术判断（创新点/结论表述由用户确认）
