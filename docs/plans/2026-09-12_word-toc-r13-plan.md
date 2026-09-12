# TOC 目录域 + 写作技能接入自动修复 Round 13 实施计划

> 日期: 2026-09-12 · 分支: `feat/word-toc-field` · 基于 main @ 00296f09
> 系列: Word 写作能力增强（R7-R12 之后的第 7 轮）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 零新增依赖（TOC 域为纯 oxml 注入；技能为纯 Markdown）。
> 冲突规避: 不触碰 journal/curator/gateway 区域。

## 背景（Round 12 合并后再分析）

1. **目录（TOC）是论文/长文档刚需**：Round 7-12 的 format_spec 覆盖了
   页面/样式/页码，但没有目录。python-docx 无法"计算"目录内容，但可以
   插入 **TOC 域**（`w:fldSimple w:instr='TOC \o "1-3" \h \z \u'`）——
   域由 Word/WPS/LibreOffice 按标题样式渲染（打开后更新域/F9 即生成），
   与生成器"标题编号交给样式"的思路一致。域内放置占位提示段落，避免
   未更新域时显示空白让用户误以为失败。
2. **Round 12 的 office_repair_word 尚未进入写作技能工作流**：两个
   SKILL.md 的"自检与修复"步骤只提 office_lint_word——补上 repair 工具
   的使用说明，形成"自检 → 自动修复 → 复检"完整闭环。

## 批次任务

### A. TOC 域（models.py + word_layout.py + word.py）

- `WordTocSpec`（pydantic）: `heading_text`（默认"目录"，≤50）/
  `levels`（默认 "1-3"，正则约束 `\d-\d` 且首≤尾）/
  `placeholder_text`（域未更新时的占位提示，默认"（目录：在 Word 中
  按 F9 或右键"更新域"生成）"，≤200）
- `WordFormatSpec.toc: Optional[WordTocSpec]`
- `word_layout.insert_toc_field(doc, toc)`: 在文档**标题之后、正文之前**
  插入——目录标题段（Heading 1 样式但**不参与**多级编号，同参考文献节
  处理）+ TOC 域段（fldSimple，占位 run 提示文本）+ 分页符
  （正文从新页开始，论文惯例）
- 生成顺序：title → [TOC] → body → bibliography

### B. Linter 对偶规则（word_lint.py）

- `toc/presence`：spec.toc 提供时，文档前部必须存在 TOC 域
  （fldSimple instr 以 "TOC" 开头），缺失 → error

### C. 技能接入 repair（两个 SKILL.md）

- 第 5 步"自检与修复"补 office_repair_word：查出的样式/编号/题注类
  违规先自动修复（默认 -repaired.docx 新文件）再复检；citation 类
  违规人工处理

### D. 测试（`backend/tests/integration/test_office_word_toc.py`）

- TOC 域插入位置（标题后正文前）/ 占位文本 / 域 instr 断言
- levels 参数映射到 instr；toc=None 零变化
- Linter toc/presence 正反例
- 两个 SKILL.md 正文含 office_repair_word（防回归）
- 不新增 LLM 工具（TOC 走 office_create 的 format_spec，无三件套变更）

## Round 14 候选

- journal fill_from_content 接入引用引擎（需与 journal 工作流协调）
- Pillow 图片管线（压缩/转格式，main 通道懒加载）
- TOC 域更新收尾（LibreOffice headless 宏 / Word COM 可选通道）
