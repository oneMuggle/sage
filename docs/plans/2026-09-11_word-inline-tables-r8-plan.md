# Word 内容元素增强 Round 8 实施计划（行内插图 + 题注编号 + 三线表 + 标题编号）

> 日期: 2026-09-11 · 分支: `feat/word-inline-images-tables` · 基于 main @ 4c5f6626
> 系列: Word 写作能力增强 P1（Round 7 版式引擎 FormatSpec #622 之后的第二轮）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 零新增依赖（纯 python-docx + oxml，图片载荷复用 charts.py 既有管线）；
> 新代码沿用 typing.Optional/List 注解风格降低未来 backport 成本。
> 冲突规避: 避开 curator 系列（#612 刚合）与 memory/embedder 区域。

## 背景（Round 7 合并后再分析）

Round 7 落地后，`generate_docx` 已支持版式级控制（页边距/样式/页眉页脚），
但**内容元素**仍是期刊论文/项目文档写作的短板：

1. **图片只能文末追加**（`req.images` 在正文之后按顺序 append），不能插到
   引用它的段落之后；无题注（"图1 xxx"），论文/报告刚需。
2. **表格是裸表格**（默认全网格边框），无三线表（学术规范）、无表题注、
   无表头跨页重复、无列宽/合并单元格控制。
3. **标题无自动编号**——多级标题"1 / 1.1 / 1.1.1"靠 LLM 手写进文本，
   改结构时编号易错。
4. **受管路径丢 images**：`_coerce_word_request` 未透传 `images`（Round 7
   前已存在的缺口，本次顺手修复）。

## 批次任务

### A. 模型扩展（`backend/office/models.py`）

- `WordImageSpec(ImageSourceSpec)` 新增:
  - `caption: Optional[str]`（题注文本，≤200 字符）
  - `after_paragraph: Optional[int]`（ge=0；插入到 `paragraphs[i]` 之后；
    None = 文末追加，保持旧行为；越界钳到末尾）
- `WordTableSpec` 新增:
  - `caption: Optional[str]`（表题注，置于表格上方）
  - `style: Optional[Literal["grid", "three_line"]]`（None = 既有默认网格）
  - `header_repeat: bool = False`（表头跨页重复，trPr/tblHeader）
  - `column_widths_cm: Optional[List[float]]`（ge=0.5 le=30，长度=列数）
  - `merges: Optional[List[WordCellMergeSpec]]`（0-based 含端点矩形合并）
- `WordCellMergeSpec`: `min_row/max_row/min_col/max_col`（ge=0，约束 ≤ 表格
  尺寸在生成期校验）
- `WordFormatSpec.numbering: bool = False`（多级标题自动编号开关）

### B. 生成器（`backend/office/word.py` + `word_layout.py`）

- **题注编号器**：图/表统一计数（图 N / 表 N 各自独立计数），题注段落
  居中、9pt（小五）。题注紧跟图片（下方）/表格（上方）。
- **行内插图**：重写 body 构建循环——先按 `after_paragraph` 建索引，
  段落写入后插入对应图片；`after_paragraph=None` 的图保持文末追加。
- **三线表**（`word_layout._apply_three_line_borders`）：tblPr/tblBorders
  top+bottom 1.5pt（sz=12 单线）、insideH/insideV/left/right none；表头
  行各单元格 tcPr/tcBorders bottom 0.75pt（sz=6）。
- **表头跨页重复**：首行 trPr 追加 `<w:tblHeader/>`。
- **列宽**：tblLayout fixed + 每列 gridCol/单元格 w。
- **合并单元格**：`table.cell(r1,c1).merge(table.cell(r2,c2))`，越界
  `OfficeGenerateError`。
- **标题编号**：body 循环内维护 h1/h2/h3 计数器，`numbering=True` 时
  给 heading 文本加 "N." / "N.M" / "N.M.K" 前缀（字面文本方案：全渲染器
  兼容、可测试；样式内自动编号 numbering part 留给后续轮次评估）。

### C. 通路（`office_create_tool.py` + `tool_service.py`）

- 工具 JSON Schema：word content 增补 images 条目字段（caption /
  after_paragraph）、tables 新字段（caption/style/header_repeat/
  column_widths_cm/merges）、format_spec.numbering。
- `_coerce_word_request`：补 `images=content.get("images")`（修受管路径
  丢图缺口）+ 其余新字段随 dict 直达请求模型，无需逐个透传的保持现状。

### D. 测试（`backend/tests/integration/test_office_word_inline_tables.py`）

- 行内插图位置断言（图片 XML 出现在目标段落之后的下一个 body 元素）
- 题注：图/表独立计数、文本/居中/9pt；无 caption 不占号
- 三线表 XML 断言（tblBorders sz/val、insideV none、表头底边 sz=6）
- header_repeat（tblHeader 存在）、列宽（gridCol w）、合并（合并后
  gridSpan/单元格数）
- 标题编号：多级前缀正确、h2 变化时 h3 重置、numbering=False 零变化
- 越界校验：after_paragraph 越界钳末尾；merges 越界报错
- 受管路径 images 透传修复回归
- 兼容性：不带新字段的旧 payload 生成结果与 Round 7 行为一致

## Round 9 候选（Word 增强 P2）

- 引用体系: SQLite 文献库 + BibTeX/RIS 导入 + GB/T 7714-2015 formatter +
  文中 [1] 标记 + 文末参考文献表
- 公式: LaTeX → OMML（期刊论文刚需）
