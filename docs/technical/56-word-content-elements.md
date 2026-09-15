# 56 — Word 内容元素增强（Round 8：行内插图/题注/三线表/标题编号）

> 日期: 2026-09-11 · 分支: `feat/word-inline-images-tables` · 方案:
> `docs/plans/2026-09-11_word-inline-tables-r8-plan.md`
> 系列: Word 写作能力增强 P1（Round 7 FormatSpec #622 的第二轮）

## 1. 问题

Round 7 落地版式引擎后，`generate_docx` 的内容元素仍有四个短板：
图片只能文末追加且无题注；表格裸样式（无三线表/表题注/表头跨页重复/
列宽/合并）；多级标题编号靠 LLM 手写易错；受管路径（`_coerce_word_request`）
丢弃 `images` 字段（直通路径却支持）。

## 2. 方案

全部为 `OfficeWordGenerateRequest` 的**可选扩展**，旧 payload 行为不变：

| 元素 | 用法 | 实现 |
|---|---|---|
| 行内插图 | `images[].after_paragraph`（0-based，插到 `paragraphs[i]` 之后） | body 循环按锚点分组插入；越界/None 钳到文末（旧行为） |
| 图题注 | `images[].caption` | 图下方居中 9pt，"图N　caption"，图号全文独立计数；**无题注不占号** |
| 表题注 | `tables[].caption` | 表上方居中 9pt，"表N　caption"，表号独立计数 |
| 三线表 | `tables[].style="three_line"` | `tblBorders` top/bottom 1.5pt（sz=12）、insideH/V none；表头单元格 `tcBorders` bottom 0.75pt（sz=6） |
| 表头跨页 | `tables[].header_repeat` | 首行 `trPr/w:tblHeader` |
| 固定列宽 | `tables[].column_widths_cm` | 逐行写 `tcW`（Word 解析以 tcW 为准）；长度≠列数直接报错 |
| 合并单元格 | `tables[].merges`（0-based 含端点矩形） | `cell.merge`；越界抛 `OfficeGenerateError` |
| 标题编号 | `format_spec.numbering` | h1/h2/h3 计数器生成 "1 / 1.1 / 1.1.1" 文本前缀，高级别出现时重置下级；**字面文本方案**（全渲染器兼容、可测试），样式级 numbering part 留待后续评估 |

实现位置：表格排版辅助在 `word_layout.py`（`apply_three_line_table` /
`enable_header_repeat` / `set_fixed_column_widths` / `apply_cell_merges` /
`add_caption` / `heading_number_prefix`），图片分组与 body 组装在 `word.py`
（`_partition_images` / `_add_inline_image` / `_style_table`）。无题注的
文末插图仍走 `doc.add_picture` 原路径（渲染逐字节一致）。

## 3. 顺带修复

- `_coerce_word_request` 透传 `images`（受管路径丢图缺口）；
- `OfficeWordGenerateRequest.images` 字段重复定义（Round 7 遗留，pydantic
  静默取后者，本轮收敛为一处）并升级为 `WordImageSpec`。

## 4. 兼容性与 Win7 对齐

新功能不 cherry-pick 到 release/win7（31-win7-lts.md §2）；零新增依赖
（纯 python-docx + oxml）；全字段 Optional/false，旧 payload 生成结果
与 Round 7 一致（测试锁定，含 tcW 默认 6 英寸不被改写断言）。

## 5. 测试

`backend/tests/integration/test_office_word_inline_tables.py` 20 项：
行内位置（body XML 顺序）、图/表独立编号、题注样式、无题注不占号、
越界钳末尾、三线表边框 XML、grid 样式、题注在表前、表头重复/列宽/
合并（含 tc 同一性断言）、长度/越界报错、编号前缀与重置、numbering
关闭零变化、受管路径透传回归、模型校验、旧 payload 兼容。

## 6. 后续（Word 增强系列）

- Round 9（P2）: 引用体系（SQLite 文献库 + BibTeX 导入 + GB/T 7714-2015
  formatter + 文中 [1] 标记 + 文末参考文献表）；LaTeX→OMML 公式
- Round 10（P3）: docx 格式 Linter + `paper-writing` / `report-writing` 技能
