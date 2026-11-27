# Word 版式控制与模板填充 P0（2026-11-26）

> 计划：[`docs/plans/2026-11-26_word-layout-template-p0.md`](../plans/2026-11-26_word-layout-template-p0.md)
> 背景：LLM_Multi 软著材料双管线实测（模板填充版 / 版式控制版）
> 状态：P0 服务端能力已实现（M1–M4）

## 1. 能力总览

| 能力 | 入口 | 说明 |
|---|---|---|
| FormatSpec 扩展 | `format_spec` / `POST /office/word/generate` | 自定义纸张、行号、字符缩进、标题行距、页眉制表位/边框/中文页码、节级页眉页脚 |
| 整块结构填充 | `POST /office/word/template/refill`、`office_refill_word_template` | 无占位符模板的段落克隆填充（h1/h2/h3/body/bold） |
| Word 格式转换 | `POST /office/word/convert`、`office_convert_word` | `.doc ↔ .docx`（LibreOffice headless / Word COM） |

三项能力共同覆盖软著类文档的两条生成路线：**模板填充**（克隆模板段落、
保留直接格式）与**版式控制**（FormatSpec 显式指定页面/页眉/行号等）。

## 2. FormatSpec 扩展（P0-2/3/4）

新增/扩展字段均在 `backend/office/models/_word_gen.py`，写入逻辑拆在
`backend/office/word_layout_sections.py`（`word_layout.py` 已接近 800 行
架构棘轮，只保留委托调用）。

### 2.1 页面与行号

```jsonc
"page": {
  "size": "A3|A4|A5|B4|B5|legal|letter",   // 命名纸张扩展
  "width_cm": 17.6, "height_cm": 25.0,      // 自定义纸张（优先于 size）
  "line_numbering": {"count_by": 1, "restart": "continuous", "start": 1}
}
```

- 行号写 `w:lnNumType`，按 sectPr schema 顺序插入（`w:pgMar` 之后、
  `w:pgNumType`/`w:cols` 之前）；
- `restart` 支持 `continuous` / `newPage` / `newSection`，与 Word 一致；
- 源程序类文档（软著代码、审计留档）用连续行号 + 固定行距即可满足
  “每页约 50 行”的提交惯例。

### 2.2 正文与标题

- `body.first_line_indent_chars`：写 `w:firstLineChars`（2 字符 = 200）并同步
  近似 `w:firstLine`（twips），优先级高于 `first_line_indent_cm`；
- `headings.hN.line_spacing`（倍数）/ `line_spacing_pt`（固定磅，优先）。

### 2.3 页眉页脚

`WordHeaderFooterSpec` 新增：

| 字段 | 作用 |
|---|---|
| `tab_right` | 页码块前插入制表符，右对齐到右边距（“左标题 + 右页码”页眉） |
| `border_bottom` | 页眉段落底部单线边框 |
| `page_number_style` | `plain`（仅 PAGE）或 `zh`（“第 PAGE 页 共 NUMPAGES 页”） |
| `font_size_pt` / `font_family` / `ascii_font` | 页眉页脚字体（含域 run） |

页码使用 `w:fldSimple`（与既有页脚一致，打开即显示缓存值；更新域后为实际值）。

### 2.4 节级页眉页脚

`WordSectionBreakSpec` 的 `page_setup` 改为可选，新增 `header`/`footer`。
`apply_section_break`（`word_layout.py`）在 `doc.add_section()` 之后写节级
页眉页脚。

**关键细节**：`python-docx` 的 `add_section()` 让新旧两节共享同一个
header/footer part；直接修改会串改前一节。写入新节页眉前必须先
`is_linked_to_previous = True → False` 完成 detach（`write_header_footer`
的 `fresh=True` 分支），测试 `test_section_break_header_is_independent`
锁定该行为。

## 3. 整块结构填充（P0-1）

`backend/office/word_template_refill.py`：

- **输入**：`blocks[{kind, text}]`（kind ∈ h1/h2/h3/body/bold），可选
  `anchors`（显式段落下标）、`start_anchor_text/start_paragraph`、
  `end_anchor_text/end_paragraph`；
- **块模板识别**：h1/h2/h3 按 `w:outlineLvl` 0/1/2 或 `Heading N` 样式；
  body 取正文区间内首个带首行缩进、非加粗、字号 ≤14pt 的段落；bold 取
  首个加粗非标题段落；缺块模板时报错（可用 anchors 指定）；
- **替换**：删除 `[start, end)` 区间的顶层段落（表格不动），逐个深拷贝
  块模板并替换首个 run 的文字（保留 rPr 与段落直接格式），插入到区间起点；
- **安全**：块模板中的书签与旧分页标记在克隆时剥离（避免重复 id），含域
  （fldChar/fldSimple）或分节符的块模板拒绝使用；输出不覆盖模板或已存在
  文件；临时文件 + 原子替换；模板/输出均在工作区内；
- **响应**：`inserted_blocks`、`removed_paragraphs`、识别到的 `anchors`、
  `warnings`（如 bold 回退到正文样式）。

与既有 `word_template_profile_fill`（占位符/内容控件/书签）互补：真实
模板大多没有占位符，块模板克隆是“模板填充”路线的兜底。

## 4. Word 格式转换（P0-5）

`backend/office/word_convert.py`：

- 转换器顺序：LibreOffice headless（`soffice --convert-to docx|doc`）→
  Windows Word COM（`SaveAs2` FileFormat 12/0）；
- 契约与 PDF 导出一致：`convert_word` **永不抛异常**，失败返回
  `WordConvertResult(ok=False, error=...)`；
- 源文件与输出限制在工作区内；默认输出 `<stem>.<目标格式>`，已存在需
  `overwrite=true`；LibreOffice 在临时子目录转换后原子移动到目标；
- 与 PDF 导出共用 `export_pdf._EXPORT_LOCK`（LibreOffice 并发实例共享 user
  profile 会互锁）；不再自建 `_CONVERT_LOCK`，避免两条路径并发拉起 soffice；
- `timeout_seconds` 双端设限：路由层 `Field(ge=1, le=1800)`，库层
  `_MAX_TIMEOUT_SECONDS` 兜底（防止绕过路由直调导致 soffice 长时间挂起）；
- Word COM 路径先 `document.Close()` + `word.Quit()` 再 `os.replace` ——
  Word 持有输出文件句柄，未释放时 Windows 上替换会 `PermissionError`；
  Office 2007（Win7 LTS 常见）没有 `SaveAs2`，自动回退 `SaveAs`。

## 5. OOXML 子元素顺序（Word 修复提示的根因）

`CT_SectPr` / `CT_PPrBase` / `CT_RPr` 都是 `xsd:sequence`，子元素顺序错乱
会让 Word 判定文档损坏并弹「文档内容有问题需要修复」。本模块写入时一律
按 schema 顺序落位：

| 容器 | 顺序表 | 典型踩坑 |
|---|---|---|
| `w:sectPr` | `_SECTPR_ORDER`（`headerReference`/`footerReference` 最前） | `pgNumType` 追加到 `docGrid` 之后；`footnotePr` 挤在中间 |
| `w:pPr` | `_PPR_ORDER` | `pBdr` 追加到 `tabs` 之后 |
| `w:rPr` | `_RPR_ORDER` | `rFonts` 插到 `rStyle` 之前 |

python-docx 的 `ZeroOrMore(..., successors=_tag_seq)` 按后继标签名列表顺序
查找插入点，会被一个位置错误的 `footnotePr` 带偏，连带把 `headerReference`
排到 `pgSz` 之后 —— 所以必须先保证自己写入的元素在 schema 位次上正确。

模板整块克隆同样会剥离 `w:footnoteReference` / `w:endnoteReference` /
`w:commentReference` / `w:commentRangeStart` / `w:commentRangeEnd`：这些引用
嵌在 run 裁剪够不到的位置（段落级批注范围、超链接内的脚注引用），保留下来
会让多个副本指向同一条 notes/comments 条目，同样触发 Word 修复提示。

## 6. API 与 Agent 工具

| 能力 | REST | Agent 工具 |
|---|---|---|
| 整块结构填充 | `POST /api/v1/office/word/template/refill` | `office_refill_word_template`（WRITE_LOCAL；file_path / doc_id） |
| 格式转换 | `POST /api/v1/office/word/convert` | `office_convert_word`（WRITE_LOCAL；file_path） |

`format_spec` 扩展无需新端点，随既有 `POST /office/word/generate` 与
`office_create` 生效。本轮不新增前端 UI（模板填充对话框的“结构填充”页签
与版式面板为后续 P1/P2）。

## 7. 测试

- `backend/tests/unit/office/test_word_layout_p0.py`：自定义纸张/行号/
  字符缩进/标题行距/页眉域与边框/节级页眉独立/向后兼容的 plain 页脚；
- `backend/tests/unit/office/test_word_ooxml_order.py`：以 ECMA-376 顺序表
  为独立 oracle，断言 `sectPr` / `pPr` / `rPr` 子元素顺序（含分节符、
  页眉页脚、已带 `rStyle` 的幂等路径）；
- `backend/tests/unit/office/test_word_template_refill.py`：自动锚点识别、
  直接格式保真、区间锚点、显式 anchors、输出安全、缺块模板与含书签
  块模板拒绝、脚注/批注引用剥离、端点委托；
- `backend/tests/unit/office/test_word_convert.py`：LibreOffice stub 成功/
  自定义文件名/无转换器/超时/覆盖策略/工作区围栏/同格式拒绝/端点委托；
- `backend/tests/unit/tools/test_office_convert_tool.py`：工具参数校验、
  委托与服务错误映射；
- `test_tool_bundles_parity.py`：工具清单快照已登记两个新工具
  （online 127 / intranet 126 / offline 122 / headless 126）。

## 8. Win7 / Python 3.8

本功能已 cherry-pick 到 release/win7（Python 3.8 + pydantic 1.x），唯一
适配点是 `_word_gen.py` 的模型定义（pydantic 1 无 `model_config`，win7 走
`backend/compat/win7/pydantic_compat.py` 的 shim，`extra="forbid"`）；
其余服务/路由/工具文件两分支逐字节一致。代码沿用
`from __future__ import annotations` + `typing.Optional/List/Dict` 注解风格；
新增零依赖（python-docx、pydantic 已在两分支捆绑）。
