# Word 首页不同页眉页脚 Round 33 实施计划

> 日期: 2026-09-15 · 分支: `feat/word-first-page-different` · 基于 main @ 2a644a1f
> 系列: Word/Office 写作能力增强第 25 轮（R15 页眉页脚读取 #689 的收口延伸）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 零新增依赖（python-docx `different_first_page_header_footer` 原生能力）。

## 背景

正式文档（论文/报告/公文）常见需求：**首页无页眉/页脚不同**（封面页）。
python-docx 原生支持 `section.different_first_page_header_footer` 开关 +
`section.first_page_header/footer` 独立内容。R15 只做了主页眉页脚的
读取，R7 只做了主页眉页脚的生成——首页差异化是页眉页脚家族的收尾。

## 批次任务

### A. 模型（models.py）

`WordFormatSpec` 新增：
- `first_page_different: bool = False`——启用首页不同
- `first_page_header: Optional[WordHeaderFooterSpec]`——首页页眉
- `first_page_footer: Optional[WordHeaderFooterSpec]`——首页页脚

### B. 布局（word_layout.py）

- `_apply_first_page(doc, spec)`：`section.different_first_page_header_footer
  = True`；对 `section.first_page_header/footer` 写文本/页码域（复用
  `_fld_char` PAGE 域 helper）
- `insert_toc_field` 不受影响

### C. 生成器（word.py）

format_spec 应用阶段：first_page_different=True 时启用开关并写首页
页眉/页脚内容。

### D. 测试（追加 test_office_word_firstpage.py）

- 开关启用后首页页眉/页脚独立写入；正文页眉不受影响
- 首页页脚含 PAGE 域
- first_page_different=False 时零变化
- format_spec 校验（extra 字段拒绝）

## Round 34 候选

- 奇偶页页眉页脚（evenAndOddHeaders）
- Pillow 阈值配置化
- TOC 真页码版（headless/COM）
