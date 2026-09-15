# Word 奇偶页页眉页脚 Round 34 实施计划

> 日期: 2026-09-16 · 分支: `feat/word-odd-even-headers` · 基于 main @ 03c8cefe
> 系列: Word/Office 写作能力增强第 35 轮（R33 首页不同 #868 的姊妹篇）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 零新增依赖（python-docx `even_page_header/footer` + settings
> `odd_and_even_pages_header_footer` 原生能力）。

## 背景（Round 33 合并后再分析）

R33 补了首页不同；正式文档的另一半需求是**奇偶页不同**（书籍排版：
奇数页章名、偶数页书名）。python-docx 1.1 原生支持：
`section.even_page_header/footer` 独立内容 + `settings.odd_and_even_pages_header_footer`
全局开关。本轮补齐。

## 批次任务

### A. 模型（models.py）

`WordFormatSpec` 新增：
- `odd_even_pages: bool = False`——启用奇偶页不同
- `even_page_header` / `even_page_footer: Optional[WordHeaderFooterSpec]`

### B. 布局（word_layout.py）

`apply_odd_even_different(doc, even_header, even_footer)`：
- `doc.settings.odd_and_even_pages_header_footer = True`（全局设置）
- 对 `section.even_page_header/footer` 写文本（断开 linked）

### C. 生成器（word.py）

format_spec 应用阶段：odd_even_pages=True 时启用并写偶数页页眉/页脚。

### D. 测试（追加 test_office_word_firstpage.py 同族或新建）

- 开关写入后 settings.odd_and_even_pages_header_footer 为 True
- 偶数页页眉/页脚内容写入
- odd_even_pages=False 零变化
- 模型校验

## Round 35 候选

- TOC 真页码版（headless/COM）
- Pillow 阈值配置化
- Word 横排分节 + 宽表组合
