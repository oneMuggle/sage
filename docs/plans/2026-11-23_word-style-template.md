# Word 样式模板系统实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Word 生成与修改以「样式模板」为一等公民——按级别/元素定义字体、字号、行距、缩进、对齐，支持命名预设、参考文档（reference.docx）生成、规则包→样式画像转换、以及给已有文档批量套用样式。

**Architecture:** 在现有 `WordFormatSpec`（版式引擎）与规则包/规范书体系之上补齐「样式画像」层：模型扩展（按样式字体、题注、表格文字、精确行距）→ 命名预设与合并解析 → 参考文档基座生成 → 规则包转换 → 已有文档套用。所有新字段 Optional，不传时旧行为逐字节不变；不新增第三方依赖；保持 pydantic v1/v2 与 Python 3.8 兼容。

**Tech Stack:** Python 3.10（主分支）/ 3.8（release/win7 兼容检查）、FastAPI、pydantic、python-docx（直接操作 styles.xml / document.xml OOXML）、pytest。

**Spec:** 本计划即方案文档；设计依据为 2026-11-23 会话中的现状评估（docs/technical/55、117–122、134 与 `backend/office/` 源码）。

## 背景与目标

现状问题（详见评估）：

1. `WordFormatSpec` 只能全局设字体（`office/word.py:482 set_doc_default_font` 对所有样式写同一字体），无法表达「一级标题黑体、正文仿宋」这类中文公文/论文的按级字体需求。
2. 题注字号硬编码 9pt（`word_layout.py:350 add_caption`），表格文字无样式参数。
3. 生成不能以 `.docx` 模板为样式源；现有 docxtpl 模板只能做占位符填充（内容模板），不是样式模板。
4. 规则包（含 GB/T 9704 公文包）与模板规则抽取（M3a）只用于审校，不能反向变成生成参数。
5. 无命名预设；前端自由创建不发 `format_spec`（`OfficeGenerateForm.tsx:322`），LLM 每次手写 spec 易漂移。
6. 修改已有文档（尤其 markdown 转出的 docx）缺少「整篇套用样式」能力。

本轮目标：完成后端 P0 能力（模型 + 预设 + 参考文档 + 规则包转换 + 已有文档套用），并同步 LLM 工具契约。Markdown 解析升级与前端 UI 留待下一轮（见「后续」）。

## 涉及的文件与模块

| 文件 | 变更 |
|---|---|
| `backend/office/models/_word_gen.py` | 扩展 `WordBodyStyleSpec`/`WordHeadingStyleSpec`；新增 `WordCaptionStyleSpec`/`WordTableTextStyleSpec`；`WordFormatSpec` 增加 `caption`/`table_text`；`OfficeWordGenerateRequest` 增加 `format_spec_preset`/`template_docx_path` |
| `backend/office/models/__init__.py` | 导出新模型 |
| `backend/office/word_layout.py` | 样式字体补丁、精确行距、题注样式、表格文字样式、公开 `apply_style_definitions` |
| `backend/office/word.py` | 预设/参考文档解析、字体默认逻辑分支、题注/表格样式接线 |
| `backend/office/word_style_presets.py`（新建） | 内置预设（default/report/gb9704-gongwen/academic-thesis）+ 深合并 `resolve_effective_format_spec` |
| `backend/office/word_style_profile.py`（新建） | 规则包 → 样式画像转换 |
| `backend/office/word_rulepack_models.py` | 新增转换结果模型 `WordStyleProfileConversion`/`WordStyleUnmappedRule` |
| `backend/office/word_style_apply.py`（新建） | 已有文档套用样式：样式定义应用、直接格式清理、dry-run、原子覆盖 |
| `backend/office/word_lint.py` | 正文字体/标题字体检查 |
| `backend/api/office_word_style_routes.py`（新建） | `GET /office/word/style-presets`、`POST /office/word/style/apply`、`POST /office/word/style/from-rulepack` |
| `backend/api/office_routes.py` | 挂载新子路由 |
| `backend/office/tool_service.py` | `_coerce_word_request` 透传 `format_spec_preset`/`template_docx_path`/`font_family`/`ascii_font` |
| `backend/tools/office_create_tool.py` | content schema 暴露 `format_spec_preset`/`template_docx_path` |
| `docs/technical/135-word-style-template.md`（新建） + `docs/technical/README.md` | 技术文档归档 |

测试文件：

- `backend/tests/unit/office/test_word_style_profile.py`
- `backend/tests/integration/test_office_word_style_template.py`
- `backend/tests/unit/office/test_word_style_from_rulepack.py`
- `backend/tests/unit/office/test_word_style_apply.py`
- 扩展 `backend/tests/integration/test_office_word_lint.py`（字体检查）

## 技术方案

### 1. 样式画像模型（`models/_word_gen.py`）

```python
class WordBodyStyleSpec(BaseModel):
    font_size_pt: Optional[float] = Field(default=None, ge=1.0, le=72.0)
    font_family: Optional[str] = Field(default=None, max_length=100)   # eastAsia
    ascii_font: Optional[str] = Field(default=None, max_length=100)    # ascii/hAnsi/cs
    line_spacing: Optional[float] = Field(default=None, ge=1.0, le=3.0)
    line_spacing_pt: Optional[float] = Field(default=None, ge=1.0, le=200.0)  # 固定行距；优先于 line_spacing
    first_line_indent_cm: Optional[float] = Field(default=None, ge=0.0, le=5.0)
    space_before_pt: Optional[float] = Field(default=None, ge=0.0, le=48.0)
    space_after_pt: Optional[float] = Field(default=None, ge=0.0, le=48.0)
    align: Optional[Literal["left", "center", "right", "justify"]] = None

class WordHeadingStyleSpec(BaseModel):
    # 原有字段不变，新增：
    font_family: Optional[str] = Field(default=None, max_length=100)
    ascii_font: Optional[str] = Field(default=None, max_length=100)

class WordCaptionStyleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    font_family: Optional[str] = Field(default=None, max_length=100)
    ascii_font: Optional[str] = Field(default=None, max_length=100)
    font_size_pt: Optional[float] = Field(default=None, ge=1.0, le=72.0)
    bold: Optional[bool] = None
    align: Optional[Literal["left", "center", "right", "justify"]] = None

class WordTableTextStyleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    font_family: Optional[str] = Field(default=None, max_length=100)
    ascii_font: Optional[str] = Field(default=None, max_length=100)
    font_size_pt: Optional[float] = Field(default=None, ge=1.0, le=72.0)
    header_bold: Optional[bool] = None

class WordFormatSpec(BaseModel):
    ...
    caption: Optional[WordCaptionStyleSpec] = None
    table_text: Optional[WordTableTextStyleSpec] = None

class OfficeWordGenerateRequest(BaseModel):
    ...
    format_spec_preset: Optional[str] = Field(default=None, max_length=80)
    template_docx_path: Optional[str] = Field(default=None, max_length=2000)
```

约定：`line_spacing_pt` 与 `line_spacing` 同时给定时 pt 优先（文档注明）；字体 None 项不触碰（保持 set_doc_default_font 的全局值）。

### 2. 样式应用（`word_layout.py`）

- `_set_style_fonts(style, font_family=None, ascii_font=None)`：写 `w:rPr/w:rFonts` 的 `eastAsia`（font_family）与 `ascii/hAnsi/cs`（ascii_font），清除 `*Theme` 属性（与 `word._patch_style_rfonts` 同理）。
- `_patch_linked_char_style(doc, style, ...)`：按 `w:link` 找到关联 character style（Heading1Char 等）并同步字体——Word 渲染时 linked char style 会覆盖段落样式 rFonts。
- `_apply_body_style`：新增字体、`line_spacing_pt`（`paragraph_format.line_spacing = Pt(x)` → `lineRule="exact"`）、`space_before_pt`。
- `_apply_heading_style`：新增字体（含 linked char style）。
- `add_caption(doc, text, *, kind, number, spec=None)`：默认 9pt 居中（旧行为）；`spec` 覆盖字号/字体/对齐/加粗。
- `apply_table_text_style(table, spec)`：对全部单元格 runs 按 spec 设置字体/字号；`header_bold` 只作用于首行。
- 新增公开 `apply_style_definitions(doc, spec)`：只应用 page/body/title/headings（不含页眉页脚文本、目录/编号等生成期项），供「已有文档套用」复用。

### 3. 命名预设（`word_style_presets.py`）

`_PRESETS: Dict[str, Tuple[name, description, WordFormatSpec]]`，模块导入时用 `WordFormatSpec(**raw)` 校验（fail fast）。

- `default`：空规范（当前行为）。
- `report`：A4，上下 2.54cm / 左右 3.18cm；正文宋体 + Times New Roman 12pt、1.5 倍行距；标题黑体 22pt 加粗居中；h1 黑体16 / h2 黑体14 / h3–h5 黑体12；题注宋体 10.5pt。
- `gb9704-gongwen`：A4 纵向，上 3.7 / 下 3.5 / 左 2.8 / 右 2.6cm；正文仿宋_GB2312 + TNR 16pt、固定行距 28pt、首行缩进 1.1cm、两端对齐；标题方正小标宋简体 22pt 居中；h1 黑体16、h2 楷体_GB2312 16、h3–h5 仿宋_GB2312 16 加粗；题注楷体_GB2312 10.5pt；页脚居中页码。
- `academic-thesis`：A4，上下 2.5 / 左 3.0 / 右 2.5cm；正文宋体 + TNR 12pt、1.5 倍；标题黑体 22 加粗居中；h1 黑体15 / h2 黑体14 加粗 / h3–h5 黑体12；题注宋体 10.5pt。

`resolve_effective_format_spec(preset_id, spec)`：preset 与显式 spec 深合并（逐字段，None 不覆盖；`headings` 按 hN 合并）；未知 preset 抛 `OfficeGenerateError("unknown_style_preset: ...")`。

`GET /office/word/style-presets` 返回 `{ok, presets:[{id,name,description}]}`。

### 4. 参考文档生成（`word.py`）

`template_docx_path` 提供时：

1. `_load_reference_document(path, workspace_path)`：workspace 内解析（`resolve_within`）、仅 `.docx`、≤20MB；打开后删除 body 除 `w:sectPr` 外的全部子元素（保留 styles/theme/numbering/页眉页脚部件与节属性）。
2. 字体默认逻辑：模板模式下未显式传 `font_family`/`ascii_font` 时**不调用** `set_doc_default_font`（保留模板字体）；显式传则覆盖全局。
3. 其余流程不变：`doc.add_heading(title, level=0)`、正文按命名样式写入，`format_spec`（含 preset）继续作为覆盖层。

请求优先级：参考文档样式 < 命名预设 < 显式 `format_spec` 字段。

### 5. 规则包 → 样式画像（`word_style_profile.py`）

`format_spec_from_rulepack(rulepack) -> WordStyleProfileConversion`：

| 规则 kind | params | 映射 |
|---|---|---|
| `page.size` | size | `page.size` |
| `page.orientation` | orientation | `page.orientation` |
| `page.margins` | top_cm/bottom_cm/left_cm/right_cm | `page.margins_cm` |
| `page.page_number` | required | `footer.page_number=True, align=center`（footer 为空时） |
| `style.font` | style/font_east_asia/font_ascii/size_pt/bold/color | Normal→body、Title→title、Heading 1–5→headings.hN、题注类样式名（图题/表题/题注/图注/表注/Caption）→caption |
| `style.paragraph` | style/line_spacing/line_spacing_pt/first_line_indent_cm/alignment/space_before_pt/space_after_pt | Normal→body、Heading N→headings.hN、题注类→caption.align |
| 其他 | — | 计入 `unmapped`（reason: `not_style_rule` / `unsupported_style` / `unsupported_field`） |

结果模型（`word_rulepack_models.py`）：

```python
class WordStyleUnmappedRule(BaseModel):
    rule_id: str
    kind: str
    reason: str

class WordStyleProfileConversion(BaseModel):
    ok: bool = True
    format_spec: WordFormatSpec
    applied_rule_ids: List[str]
    unmapped: List[WordStyleUnmappedRule]
    warnings: List[str]
```

`POST /office/word/style/from-rulepack`：body `{workspace_path, rulepack_id?, rulepack?}`；未传 id/内联时用默认规则包（与 audit 路由一致）。

### 6. 已有文档套用样式（`word_style_apply.py`）

`apply_style_to_document(file_path, spec, *, clear_direct_formatting=False, dry_run=False, overwrite=False) -> Dict[str, Any]`：

1. 校验文件（workspace 内、`.docx`、≤50MB）。
2. 快照 Normal/Title/Heading1–5 的字体/字号/行距/对齐（before）。
3. `apply_style_definitions(doc, spec)`。
4. `clear_direct_formatting=True` 时移除正文与表格 runs 的直接字体格式（`w:rFonts`/`w:sz`/`w:szCs`/`w:color`），保留加粗/斜体等语义强调；返回清理 run 数。
5. 生成 after 快照与 `styles_changed` 列表。
6. `dry_run=True` 不落盘；否则默认写 `<stem>-styled.docx`（`overwrite=True` 时临时文件原子替换原文件，复用 `edit._atomic_replace`）。

`POST /office/word/style/apply` 请求：`{workspace_path, file_path, format_spec_preset?, format_spec?, clear_direct_formatting?, overwrite?, output_filename?, dry_run?}`。

### 7. Lint 字体检查（`word_lint.py`）

- `body.font_family/ascii_font` → 检查 Normal 样式 `w:rFonts`（eastAsia / ascii），不匹配报 error（rule_id `body/font_family` / `body/ascii_font`）。
- `title`/`headings.hN` 字体同理（`title/font_family`、`heading/{n}/font_family`）。

### 8. 工具与受管路径

- `tool_service._coerce_word_request`：透传 `format_spec_preset`、`template_docx_path`、`font_family`、`ascii_font`（修复受管路径丢全局字体的既有缺口）。
- `office_create_tool` content schema：description + properties 增加两项（`format_spec_preset` 字符串枚举提示、`template_docx_path` workspace 相对路径说明），直通路径透传。

## 实施步骤

### Task 1：样式画像模型 + 生成侧应用

**Files:** `models/_word_gen.py`、`models/__init__.py`、`word_layout.py`、`word.py`
**Test:** `backend/tests/integration/test_office_word_style_template.py`

- [ ] 写失败测试：生成时 `format_spec.body.font_family="仿宋_GB2312"`、`headings.h1.font_family="黑体"`、`line_spacing_pt=28` → 回读 Normal rFonts eastAsia=仿宋_GB2312、Heading 1 rFonts eastAsia=黑体、Normal 段落 `line_spacing` 为 28pt；不传新字段时旧断言不变。
- [ ] 写失败测试：`caption` spec（字号 10.5/楷体/居左）→ 题注段落 runs 字号 10.5、eastAsia=楷体、对齐 left；`table_text` spec → 表内 runs 字号 10.5、表头加粗。
- [ ] 运行测试确认失败（字段不存在 → ValidationError）。
- [ ] 实现模型与 `word_layout` 应用逻辑（含 linked char style 同步、`Pt()` 精确行距、题注/表格样式），`word.py` 接线（caption/table_text 传入）。
- [ ] 运行新测试 + `test_office_word_format_spec.py` + `test_office_word_inline_tables.py` 全绿。
- [ ] commit：`feat(office): Word 样式画像——按级字体/精确行距/题注与表格文字样式`

### Task 2：Lint 字体检查

**Files:** `word_lint.py`
**Test:** `backend/tests/integration/test_office_word_lint.py`

- [ ] 写失败测试：生成带字体 spec 的文档后 lint 通过；把 Normal 字体改错 → `body/font_family` error 出现；同理 Heading 1。
- [ ] 实现 `_style_fonts` 读取与两项检查，接入 `checked` 列表。
- [ ] 运行 lint 全量测试。
- [ ] commit：`feat(office): Word Linter 增加样式字体检查`

### Task 3：命名预设 + 合并解析 + 端点

**Files:** `word_style_presets.py`（新建）、`office_word_style_routes.py`（新建，先只含 presets 端点）、`office_routes.py`、`word.py`
**Test:** `backend/tests/unit/office/test_word_style_profile.py`

- [ ] 写失败测试：`list_style_presets()` 含 4 个 id；`resolve_effective_format_spec("gb9704-gongwen", None)` 的 body 为仿宋 16pt/28pt 固定行距；显式 spec 覆盖 `body.font_size_pt=12` 时其余预设字段保留；未知 id 抛 `OfficeGenerateError`。
- [ ] 写失败测试：`OfficeWordGenerateRequest(format_spec_preset="report", ...)` 生成后 Normal 为宋体 12pt、标题黑体。
- [ ] 实现预设数据、深合并、`generate_docx` 内 `spec = resolve_effective_format_spec(...)`（替换全部 `req.format_spec` 引用）、GET 端点与路由挂载。
- [ ] 运行预设 + FormatSpec 回归测试。
- [ ] commit：`feat(office): Word 命名样式预设（公文/论文/报告）`

### Task 4：参考文档生成

**Files:** `word.py`
**Test:** `backend/tests/integration/test_office_word_style_template.py`

- [ ] 写失败测试：用 python-docx 构造模板 docx（Normal 设为 华文楷体 13pt、标题段落文本"模板残留"）→ 以 `template_docx_path` 生成新文档：Normal eastAsia=华文楷体、正文不含"模板残留"；显式 `font_family="宋体"` 时覆盖为宋体；相对路径解析到 workspace；越界/非 docx 报错。
- [ ] 实现 `_load_reference_document` + 字体默认逻辑分支。
- [ ] 运行新测试 + FormatSpec 兼容测试。
- [ ] commit：`feat(office): Word 参考文档（reference.docx）生成`

### Task 5：规则包 → 样式画像转换

**Files:** `word_rulepack_models.py`、`word_style_profile.py`（新建）、`office_word_style_routes.py`
**Test:** `backend/tests/unit/office/test_word_style_from_rulepack.py`

- [ ] 写失败测试：内置 `gb-t-9704-general` 转换 → page A4/纵向/边距、body 仿宋_GB2312 16pt、footer 页码；自定义规则包含 Heading 1 黑体 + 图题楷体 → 映射到 headings.h1/caption；未知样式与 content 规则进入 `unmapped`。
- [ ] 实现映射函数与结果模型；实现 POST 端点（rulepack_id 加载复用 audit 路由逻辑）。
- [ ] 运行转换测试 + 路由集成测试。
- [ ] commit：`feat(office): 规则包转换为 Word 样式画像`

### Task 6：已有文档套用样式

**Files:** `word_style_apply.py`（新建）、`office_word_style_routes.py`
**Test:** `backend/tests/unit/office/test_word_style_apply.py`

- [ ] 写失败测试：构造带直接字体格式的 docx → 套用 `report` 预设后 Normal/Heading 定义变化、默认输出 `<stem>-styled.docx`、源文件不变；`clear_direct_formatting=True` 清掉 run 级 `w:sz`/`w:color` 但保留 bold；`dry_run=True` 不落盘且返回 styles_changed；`overwrite=True` 原子覆盖；幂等（二次应用 changed 为空）。
- [ ] 实现 apply 模块与端点。
- [ ] 运行 apply 测试 + office 回归。
- [ ] commit：`feat(office): 已有 Word 文档批量套用样式模板`

### Task 7：工具/受管路径契约 + 技术文档

**Files:** `tool_service.py`、`office_create_tool.py`、`docs/technical/135-word-style-template.md`、`docs/technical/README.md`
**Test:** `backend/tests/unit/tools/test_office_create_tool.py`（既有文件扩展）

- [ ] 写失败测试：`_coerce_word_request` 透传 preset/参考文档/全局字体；`OfficeCreateTool` content 携带 `format_spec_preset` 时产物样式生效。
- [ ] 实现透传与 schema 描述。
- [ ] 运行工具测试 + 契约测试（`test_ipc_manifest_routes.py`、office 全量）。
- [ ] 写技术文档 135（能力边界、接口、预设表、映射表、坑）并更新 README 索引。
- [ ] commit：`feat(office): 样式模板工具契约 + 技术文档 135`

### Task 8：全量验证与收尾

- [ ] `home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/office backend/tests/integration/test_office_word_*.py -q`（worktree 内绝对路径）
- [ ] ruff check 改动文件；py38 兼容脚本；architecture 棘轮（新增文件行数入 baseline）。
- [ ] 更新本计划勾选状态；汇报变更与遗留项。

## 风险评估与依赖

| 风险 | 缓解 |
|---|---|
| 主题字体引用覆盖显式字体（日文 Word 渲染错字体） | `_set_style_fonts` 清除 `*Theme` 属性，并同步 linked char style |
| 参考文档携带模板正文/页眉占位符 | 清空 body（仅留 sectPr）；页眉页脚保留（属样式的一部分），文档注明 |
| 参考文档安全（zip 炸弹/路径穿越） | workspace 解析 + 扩展名/大小上限；不执行外部关系 |
| 直接格式覆盖样式（markdown 转换文档常见） | `clear_direct_formatting` 显式可选，保留 bold/italic 语义；dry-run 先看 diff |
| 预设与显式 spec 合并歧义 | 逐字段深合并；文档明确「参考文档 < 预设 < 显式 spec」优先级 |
| win7/py38 兼容 | 全部 typing.Optional/List/Dict；无 PEP 585；pydantic v1/v2 字段枚举兼容 |
| 现有测试逐字节兼容 | 全部新字段 Optional；`resolve_effective_format_spec(None, None)` 返回 None；不改变旧路径 |
| 行距单位混淆 | `line_spacing_pt` 写 `Pt()`（lineRule=exact），与倍数的 `line_spacing` 分开，pt 优先 |

## 后续（不在本轮）

1. Markdown 解析升级：bold/italic/链接/图片/表格/引用 → 命名样式（`markdown_to_paragraphs.py`）。
2. 前端：自由创建「版式」下拉、模板库样式模板分区、套用模板入口、交付抽屉 lint 用所选模板。
3. LLM 工具：`office_apply_word_style`（WRITE_LOCAL）与 `office_style_from_rulepack`（READ）注册及 golden 快照同步。
4. 工作区级样式模板持久化（复用 `spec_library` 绑定模型）与发布双分支（win7）同步。

## 验收标准

- 四条链路可用：`format_spec`（含 preset）生成、reference docx 生成、规则包转样式画像、已有文档套用样式。
- 不传任何新参数时，所有既有 Office 测试逐字节语义不变。
- `gb9704-gongwen` 预设生成的文档可被 `gb-t-9704-general` 规则包审校通过（页面/边距/正文仿宋三号）。
- ruff / py38 兼容 / architecture 棘轮全绿。
