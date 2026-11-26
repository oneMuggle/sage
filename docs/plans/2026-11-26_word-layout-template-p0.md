# Word 版式控制与模板填充 P0 实施计划

> 日期：2026-11-26　分支：`feat/word-template-layout-p0`
> 依据：`/home/fz/project/软著/分析报告-Sage-Word版式控制与模板填充能力.md`（LLM_Multi 软著材料双管线实测）

## 背景与目标

软著材料实测暴露了 Sage Word 能力栈的五个 P0 缺口：

1. **无占位符模板的整块结构填充缺失**（docxtpl 需要模板预埋占位符/控制流，真实模板多为直接格式）；
2. **页眉页脚只写第一节**，无节级页眉页脚；
3. **不支持行号** `w:lnNumType`（源程序类文档必需）；
4. **版式颗粒度不足**：纸张仅 A4/letter、缩进无字符单位、页眉无制表位与边框、标题无行距；
5. **二进制 `.doc` 无法加载/填充**。

本计划交付 P0 的**服务端能力**（模型 + 服务 + API + Agent 工具 + 测试 + 文档），使 Sage 能直接复现软著类文档的两条生成路线：

- 路线 A（模板填充）：`POST /api/v1/office/word/template/refill` 克隆模板段落结构：
  无占位符、直接格式的模板也能整块替换内容；
- 路线 B（版式控制）：`format_spec` 扩展后可通过 `POST /api/v1/office/word/generate`
  表达“A4 + 页眉域/边框/制表位 + 节级页眉 + 行号 + 2 字符缩进 + 固定行距”。

**非目标（后续计划）**：渲染回环（docx→PDF→版面 diff）、前端可视化面板、批量生成、模板 lint 扩展、原生 `w:numPr` 多级编号（P1/P2）。

## 涉及文件

| 模块 | 文件 |
|---|---|
| 模型 | `backend/office/models/_word_gen.py`（扩展）、`backend/office/models/_word_refill.py`（新增）、`backend/office/models/__init__.py`（导出） |
| 版式引擎 | `backend/office/word_layout.py`（接线）、`backend/office/word_layout_sections.py`（新增：页眉页脚/行号/纸张写入）、`backend/office/word.py`（分节处传 header/footer） |
| 结构填充 | `backend/office/word_template_refill.py`（新增）、`backend/api/office_word_template_profile_routes.py`（新增端点）、`backend/tools/office_template_tool.py`（新增工具）+ `backend/tools/tool_bundles.py` / `backend/tools/__init__.py`（注册） |
| 文档转换 | `backend/office/word_convert.py`（新增，复用 `export_pdf` 的 soffice 定位）、`backend/api/office_word_convert_routes.py`（新增路由）、`backend/api/office_routes.py`（挂载）、`backend/tools/office_convert_tool.py`（新增工具） |
| 测试 | `backend/tests/unit/office/test_word_layout_p0.py`、`test_word_template_refill.py`、`test_word_convert.py`；`test_word_template_profile.py`（补充） |
| 文档 | `docs/technical/176-word-template-refill-and-layout-p0.md`、`docs/technical/README.md`（索引）、`docs/technical/55-word-format-spec-engine.md`（字段补充） |

## 技术方案

### M1 版式参数扩展（P0-2/3/4）

**模型新增/扩展**（全部 Optional/默认值，`None` 保持历史行为）：

- `WordLineNumberingSpec`：`count_by`（1–10）、`restart`（continuous/newPage/newSection）、`start`；
- `WordPageSetupSpec`：`size` 扩展 A3/A5/B4/B5/legal，新增 `width_cm`/`height_cm`（自定义纸张，优先于命名纸张）、`line_numbering`；
- `WordBodyStyleSpec.first_line_indent_chars`：按字符缩进（写 `w:firstLineChars`，优先于 cm）；
- `WordHeadingStyleSpec`：`line_spacing` / `line_spacing_pt`（固定磅优先）；
- `WordHeaderFooterSpec`：`tab_right`（右对齐制表位）、`border_bottom`（下边框）、`font_size_pt`/`font_family`/`ascii_font`、`page_number_style`（`plain`/`zh`；`zh` = “第 X 页 共 Y 页”，PAGE + NUMPAGES 域）；页眉也允许页码；
- `WordSectionBreakSpec`：`page_setup` 改为可选；新增 `header`/`footer`（该节独立页眉页脚）。

**写入实现**：

- 新增 `word_layout_sections.py` 承载页眉页脚/行号/纸张写入，`word_layout.py` 只做委托，
  以守住 800 行架构棘轮（`architecture-policy.json` `maxFileLines: 800`，word_layout 现 766 行且不在基线）；
- 节级页眉的关键细节：`doc.add_section()` 会让新旧两节共享同一个 header part；
  写入新节页眉前必须 `is_linked_to_previous = True → False` 完成“detach”，
  否则修改会串改前一节页眉（用测试锁定）；
- 页码使用 `w:fldSimple`（与现有 footer 一致，打开即显示）；`zh` 形态按
  run/fldSimple 交错顺序生成；
- 所有新增字段默认不触碰文档，既有快照/测试零变化。

### M2 整块结构填充（P0-1）

新增服务 `word_template_refill.py`：

- **输入**：`blocks[{kind: h1/h2/h3/body/bold, text}]` + 可选 `anchors`（显式段落下标）
  + `start_anchor_text` / `start_paragraph`、`end_anchor_text` / `end_paragraph`；
- **块模板自动识别**（按模板直接格式）：
  - h1/h2/h3：`w:outlineLvl` 0/1/2 或 `Heading N` 样式；
  - body：正文起点的首个非空段落（优先带首行缩进、字号 ≤14pt、非全加粗）；
  - bold：首个加粗、无大纲级别、字号 ≤14pt 的段落；
- **替换**：删除 `[start, end)` 区间段落（表格不动），逐个深拷贝块模板并替换首个 run 文字
  （保留其余 run 的 rPr/段落直接格式），插入到区间起点；含书签/域/分节符的块模板拒绝使用；
- **安全**：输出不覆盖模板/已有文件，工作区围栏（`resolve_within`），临时文件 + 原子替换；
- **API**：`POST /api/v1/office/word/template/refill`（`office_word_template_profile_routes.py`）；
- **Agent 工具**：`office_refill_word_template`（file_path / doc_id 双模式，复用 `_resolve_template_input`）。

### M3 `.doc` 转换（P0-5）

新增 `word_convert.py`：

- `soffice --headless --convert-to <docx|doc> --outdir ... <src>`，argv 列表、超时、串行锁
  （复用 `export_pdf` 的 `_locate_soffice` 逻辑，抽为包内公共函数）；
- Windows 回退 Word COM（`SaveAs2` FileFormat 12 / 0）；
- 契约为“不抛异常”，返回 `WordConvertResult(ok, method, output_path, error)`；
- 输入/输出均限制在工作区内；默认输出 `<stem>.<ext>`，存在则拒绝，支持 `output_filename`；
- **API**：`POST /api/v1/office/word/convert`（新路由文件，挂载于 `office_routes.py`）；
- **Agent 工具**：`office_convert_word`（WRITE_LOCAL）。

### M4 测试与文档

- 单元测试覆盖：新字段写入（纸张/行号/字符缩进/标题行距/页眉域/节级页眉）、
  块识别与克隆保真（模仿软著模板的直接格式）、输出安全、转换器失败契约（stub）；
- 回归：既有 office 单元/集成测试全绿；`scripts/architecture-check.mjs` 无新增违规；
- 技术文档新增第 176 章并在 README 索引登记；补 `55-word-format-spec-engine.md` 字段说明。

## 实施步骤

- [x] M1.1 模型扩展（`_word_gen.py`）+ 单元测试（RED → GREEN）
- [x] M1.2 `word_layout_sections.py` 写入实现 + `word_layout.py` 委托 + `word.py` 分节接线
- [x] M2.1 块模板识别与克隆填充服务（`word_template_refill.py`）+ 测试
- [x] M2.2 API 端点 + Agent 工具 + 注册 + 测试
- [x] M3 `.doc` 转换服务 + 路由 + 工具 + stub 测试
- [x] M4 技术文档 176 + 索引 + 格式引擎章节补充
- [x] 全量回归：office 单元/集成测试（1550 passed / 2 skipped）、架构棘轮、ruff

## 风险评估

| 风险 | 应对 |
|---|---|
| `word_layout.py` 触及 800 行棘轮 | 新逻辑放 `word_layout_sections.py`，主文件仅加委托调用 |
| 节级页眉共享 header part 导致串改 | detach 链接后再写，测试锁定“前言节不变、新节独立” |
| 自动块识别在异常模板上误判 | 支持显式 `anchors` 覆盖；响应返回识别结果与警告；缺块模板时报错 |
| 克隆段落的书签/域 id 冲突 | 书签与旧分页标记克隆时剥离；域/分节符块模板拒绝 |
| 转换依赖本机 LibreOffice/Word | 服务返回结构化失败；CI 用 stub 覆盖命令与失败路径 |
| win7/py38 语法 | 全部使用 `typing.*` 泛型与 `from __future__ import annotations` |
| 既有行为变化 | 新字段全 Optional；不传时产物逐字节等价；既有测试作为回归闸 |

## 验收标准

1. 新增/变更单元测试全绿，既有 office 测试全绿；
2. `POST /word/template/refill` 可对“无占位符、直接格式”的说明书模板完成 h1/h2/正文/加粗四类块的整块替换，克隆段落字号/缩进/加粗保持；
3. `format_spec` 可产出：自定义纸张/行号/2 字符缩进/标题行距/带边框与右对齐页码的页眉/节级页眉；
4. `/word/convert` 在无转换器的环境中返回明确错误而非异常；stub 环境下命令与输出正确；
5. 架构棘轮与 ruff 通过；技术文档 176 章 + 索引更新。
