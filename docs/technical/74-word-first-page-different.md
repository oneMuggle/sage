# 74 — Word 首页不同页眉页脚（Round 33）

> 日期: 2026-09-15 · 分支: `feat/word-first-page-different`
> 系列: Word/Office 写作能力增强第 34 轮（R15 页眉页脚读取 #689 的收口延伸）

## 1. 定位

正式文档（论文/报告/公文）常见需求：**首页无页眉/页脚不同**（封面页）。
python-docx 原生支持 `section.different_first_page_header_footer` 开关 +
`section.first_page_header/footer` 独立内容。R15 只做了主页眉页脚的读取，
R7 只做了主页眉页脚的生成——首页差异化是页眉页脚家族的收尾。

## 2. 变更

- `WordFormatSpec` 新增：
  - `first_page_different: bool = False`——启用首页不同
  - `first_page_header` / `first_page_footer: WordHeaderFooterSpec`——首页独立内容
- `word_layout.apply_first_page_different(doc, header, footer)`：
  `different_first_page_header_footer = True` + 写首页页眉/页脚文本 +
  PAGE 域（fldSimple，与主页脚一致）
- `_write_hf_text(section, kind, spec)`：向首页页眉/页脚写入 spec.text；
  linked_to_previous 断开处理
- `generate_docx`：format_spec 应用阶段接线

## 3. Win7 对齐与测试

零新增依赖；不 cherry-pick（31-win7-lts.md §2）。
`test_office_word_firstpage.py` 4 项：首页独立页眉/页脚写入、首页页脚
PAGE 域、first_page_different=False 零变化、模型字段。word 全家族回归
34 项 + ruff/tsc/eslint 全绿。

## 5. Round 34 候选

奇偶页页眉页脚（evenAndOddHeaders）、TOC 真页码版（headless/COM）、
Pillow 阈值配置化。
