# 164 — Word 样式模板（样式画像 / 预设 / 参考文档 / 规则包转换 / 已有文档套用）

> 状态：已实现（一期 2026-11-23 `feat/word-style-template`；二期 M2 `feat/word-style-template-m2`）
> 相关代码：`backend/office/word_style_presets.py`、`word_style_profile.py`、`word_style_apply.py`、`word_layout.py`、`word_lint.py`、`markdown_to_paragraphs.py`、`style_template_store.py`、`style_template_models.py`、`backend/api/office_word_style_routes.py`、`backend/tools/office_word_intelligence_tools.py`
> 相关文档：[55 版式引擎](./55-word-format-spec-engine.md)、[117 文档画像](./117-word-document-profile.md)、[119 规则包审校](./119-word-rulepack-audit.md)、[120 规则抽取](./120-word-rule-extraction.md)、[134 AI 文档工作台](./134-office-ai-workbench.md)

## 1. 能力边界

| 能力 | 入口 | 说明 |
|------|------|------|
| 按样式字体 | `format_spec.body/headings/title` 的 `font_family`/`ascii_font` | 标题黑体、正文仿宋等按级字体，写 styles.xml rFonts 并同步 linked character style |
| 精确行距 | `format_spec.body.line_spacing_pt` | 固定磅值（`w:lineRule="exact"`），如公文 28 磅；优先于倍数 `line_spacing` |
| 题注样式 | `format_spec.caption` | 字号/字体/加粗/对齐（默认 9pt 居中不变） |
| 表格文字样式 | `format_spec.table_text` | 单元格字体/字号，`header_bold` 只作用于表头首行 |
| 命名预设 | `format_spec_preset` | `default` / `report` / `gb9704-gongwen` / `academic-thesis` |
| 参考文档 | `template_docx_path` | 以任意 `.docx` 的 styles/theme/页面/页眉页脚为基座，正文清空 |
| 规则包 → 样式画像 | `POST /office/word/style/from-rulepack` | 把规则包/规范书（含模板抽取结果）编译为 `format_spec` |
| 已有文档套用样式 | `POST /office/word/style/apply` | 按画像批量重排样式定义，可选清除直接格式、dry-run、原子覆盖 |
| 字体 Lint | `word_lint` 新增规则 | `body/font_family`、`body/ascii_font`、`headings/hN/font_family`、`body/line_spacing_pt` |
| Markdown 命名样式（M2） | `content` Markdown / `paragraphs[].runs` | bold/italic → Strong/Emphasis 字符样式；链接 → Hyperlink + `w:hyperlink`；`> 引用` → Quote；表格/图片结构化，见 §11 |
| 工作区样式模板（M2） | `GET/POST /office/word/style-templates` | 规则包/预设/自定义画像存快照，工作区隔离；默认模板只用于前端下拉预选，见 §12 |
| LLM 工具（M2） | `office_style_from_rulepack`（READ）/ `office_apply_word_style`（WRITE_LOCAL） | 规则包→画像、已有文档套用；均需工具上下文，见 §13 |
| 前端入口（M2） | 生成页「版式」下拉、模板库样式模板分区、预览「套用样式」、交付抽屉 Lint | 见 §14 |

优先级：**参考文档样式 < 命名预设 < 显式 `format_spec` 字段**（逐字段深合并，None 不覆盖）。

## 2. 样式画像模型

`backend/office/models/_word_gen.py`：

```python
WordBodyStyleSpec:  font_size_pt / font_family / ascii_font / line_spacing /
                    line_spacing_pt / first_line_indent_cm / space_before_pt /
                    space_after_pt / align
WordHeadingStyleSpec: font_size_pt / font_family / ascii_font / bold / color /
                      align / space_before_pt / space_after_pt
WordCaptionStyleSpec: font_family / ascii_font / font_size_pt / bold / align
WordTableTextStyleSpec: font_family / ascii_font / font_size_pt / header_bold
WordFormatSpec:      … + caption / table_text
OfficeWordGenerateRequest: … + format_spec_preset / template_docx_path
```

全部新字段 Optional；不传时生成结果与历史版本逐字节语义一致。

## 3. 内置预设

| id | 场景 | 关键参数 |
|----|------|----------|
| `default` | 历史默认 | 空规范（不改任何样式） |
| `report` | 通用报告 | A4；正文宋体/TNR 12pt、1.5 倍；标题黑体 22；h1–h5 黑体 16/14/12；题注宋体 10.5 |
| `gb9704-gongwen` | 党政机关公文 | A4 纵向，上 3.7/下 3.5/左 2.8/右 2.6cm；正文仿宋_GB2312 16pt、固定行距 28pt、首行缩进 1.1cm、两端对齐；标题方正小标宋简体 22pt；h1 黑体 16、h2 楷体_GB2312 16、h3–h5 仿宋 16 加粗；题注楷体 10.5；页脚居中页码 |
| `academic-thesis` | 学术论文（通用） | A4，上 2.5/下 2.5/左 3.0/右 2.5cm；正文宋体/TNR 12pt、1.5 倍；标题黑体 22；h1 黑体 15、h2 黑体 14、h3–h5 黑体 12；题注宋体 10.5 |

`resolve_effective_format_spec(preset_id, spec)` 负责深合并；未知 preset 抛 `OfficeGenerateError`（不静默降级）。

验收事实：`gb9704-gongwen` 预设生成的文档通过内置 `gb-t-9704-general` 规则包审校（0 issue），测试 `test_gb9704_preset_passes_gb_rulepack_audit` 锁定。

## 4. 参考文档（reference.docx）

- 打开模板后删除 body 除 `w:sectPr` 外全部子元素：styles.xml / theme / numbering / 页眉页脚部件与节属性保留，模板正文与占位符不进入产物。
- 模板模式下未显式传 `font_family`/`ascii_font` 时**不调用** `set_doc_default_font`（保留模板字体）；显式传则全局覆盖。
- 路径：相对路径按 `workspace_path` 解析并限制在工作区内；无工作区时要求绝对路径；仅 `.docx`、≤ 20MB。
- 页眉页脚按「样式基座」保留——如果模板页眉带占位符，用户需自行替换。

## 5. 规则包 → 样式画像

`format_spec_from_rulepack(pack) -> WordStyleProfileConversion`：

| kind | 映射 |
|------|------|
| `page.size` / `page.orientation` / `page.margins` | `format_spec.page`（边距取 `top_cm` 等，忽略 `tolerance_cm`） |
| `page.page_number` | `footer.page_number=true, align=center`（required=false → unmapped） |
| `style.font` | Normal→body、Title→title、Heading 1–5→headings.hN、题注类样式（图题/表题/题注/图注/表注/Caption…）→caption |
| `style.paragraph` | 行距/缩进/段距/对齐 → body 或 headings；题注只映射 align |

护栏：数值按模型边界校验（超界 → unmapped，不静默截断）；同字段冲突保留先出现值并记 warning；`italic`/body `bold`/`color` 等暂不支持字段记 warning。返回 `applied_rule_ids` / `unmapped[{rule_id, kind, reason}]` / `warnings`。

## 6. 已有文档套用样式

`POST /api/v1/office/word/style/apply`：

```json
{
  "workspace_path": "/ws",
  "file_path": "draft.docx",
  "format_spec_preset": "gb9704-gongwen",
  "clear_direct_formatting": true,
  "dry_run": false,
  "overwrite": false
}
```

- 只应用样式定义（页面/正文/标题）；不改写正文与页眉页脚文本；目录/编号/参考文献等生成期特性不适用；
- `caption`/`table_text` 对既有内容跳过（response `warnings` 说明）；
- `clear_direct_formatting`：移除正文/表格 runs 的 `w:rFonts`/`w:sz`/`w:szCs`/`w:color`，**保留**加粗/斜体等语义强调；
- 默认输出 `<stem>-styled.docx`；`overwrite=true` 临时文件原子替换；`dry_run=true` 只返回 `styles_changed` 不落盘；
- 幂等：对已套用的文档再次应用，`styles_changed` 为空。

## 7. LLM 工具契约（office_create）

`content` 新增：

```json
{
  "format_spec_preset": "gb9704-gongwen",
  "template_docx_path": "templates/gongwen.docx",
  "format_spec": {"body": {"font_family": "仿宋_GB2312", "line_spacing_pt": 28}}
}
```

- `office_create` 工具 schema 的 `format_spec` 属性集合与 `WordFormatSpec` 模型字段由契约测试强制全等（新增字段必须同步 schema，否则测试红）；
- 受管路径 `_coerce_word_request` 同步透传 `format_spec_preset`/`template_docx_path`/`font_family`/`ascii_font`（修复受管路径此前丢弃全局字体的缺口）；
- 前端 `src/shared/api/types.ts` 的 `WordFormatSpec` 契约测试同样锁定模型字段覆盖。

## 8. 接口一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/office/word/style-presets` | 列出内置预设（id/name/description） |
| POST | `/api/v1/office/word/style/from-rulepack` | 规则包/规范书 → 样式画像（body 支持 `rulepack_id` 或内联 `rulepack`） |
| POST | `/api/v1/office/word/style/apply` | 已有文档套用样式画像（dry-run / overwrite / clear_direct_formatting；M2 起支持 `style_template_id`） |
| GET | `/api/v1/office/word/style-templates?workspace_path=` | 列出工作区样式模板（不含默认模板的隐式应用） |
| POST | `/api/v1/office/word/style-templates` | 保存模板：`format_spec` 原样 / `format_spec_preset` 展开 / `rulepack_id`\|`pack` 转换 |
| POST | `/api/v1/office/word/style-templates/{id}/activate` | 设该模板为工作区默认（生成接口不隐式应用） |
| DELETE | `/api/v1/office/word/style-templates/default` | 清除工作区默认模板 |
| DELETE | `/api/v1/office/word/style-templates/{id}` | 删除模板（仅限该工作区） |
| POST | `/api/v1/office/word/generate` | 请求新增 `format_spec_preset` / `template_docx_path` / `style_template_id` |

## 9. 坑与注意事项

- **theme 字体引用**：显式字体必须先清 `w:*Theme` 属性（日语 Word 会解析 theme 为 ＭＳ ゴシック）；样式字体还要同步 `<w:link>` 关联的 HeadingNChar/TitleChar。
- **行距单位**：`line_spacing` 是倍数（float）、`line_spacing_pt` 是固定磅值（`Pt()` → `lineRule="exact"`）；同时给出时 pt 优先。
- **直接格式覆盖样式**：`clear_direct_formatting` 只清字体相关元素，保留 b/i/u；段落级直接格式（pPr 缩进/行距）不清除，避免破坏用户手工排版。
- **参考文档**：正文清空但页眉页脚保留；`.docm`/非 docx 拒绝；大小 ≤ 20MB；相对路径必须落在工作区内。
- **规则转换顺序即优先级**：同一字段冲突保留先出现值并记 warning；需要「后出现优先」时应先对规则包排序。
- **样式快照**：`styles_changed` 只跟踪 Normal/Title/Heading 1–5；caption/table_text 是 run 级、不在快照内。
- **win7/py38**：新代码全部 `typing.Optional/List/Dict`（无 PEP 585）；`_model_field_names` 兼容 pydantic v1 `__fields__`/v2 `model_fields`；cherry-pick 时沿用既有 pydantic 兼容技巧。

## 10. 测试索引

| 文件 | 覆盖 |
|------|------|
| `backend/tests/integration/test_office_word_style_template.py` | 按级字体/精确行距/题注/表格文字/参考文档 |
| `backend/tests/integration/test_office_word_lint.py` | 字体与精确行距 Lint 规则 |
| `backend/tests/unit/office/test_word_style_profile.py` | 预设数据/深合并/生成效果/公文规则包审校闭环 |
| `backend/tests/unit/office/test_word_style_from_rulepack.py` | 规则包映射/冲突/非法值/端点 |
| `backend/tests/unit/office/test_word_style_apply.py` | 套用样式/dry-run/直接格式清理/幂等/覆盖 |
| `backend/tests/unit/tools/test_office_create_tool.py` | 工具直通路径 preset/参考文档 |
| `backend/tests/unit/tools/test_office_create_schema_contract.py` | schema/types.ts 防漂移 |
| `backend/tests/unit/office/test_markdown_to_paragraphs.py` | 内联 runs / 引用 / 表格 / 图片解析 |
| `backend/tests/integration/test_office_word_markdown_styles.py` | Markdown → 命名样式渲染闭环 |
| `backend/tests/unit/office/test_style_template_store.py` | 样式模板 CRUD / 工作区隔离 |
| `backend/tests/unit/tools/test_office_word_intelligence_tools.py` | 两个新 LLM 工具（列于该文件内） |
| `src/features/office/__tests__/GenerateWorkspace.test.tsx` | 版式下拉透传 / 交付抽屉接线 |
| `src/features/office/__tests__/WordStyleTemplateLibrary.test.tsx` | 模板库样式模板分区 |
| `src/features/office/__tests__/WordStyleApplyDialog.test.tsx` | 已有文档套用样式对话框 |
| `src/features/office/__tests__/OfficeDeliveryDrawer.test.tsx` | 交付抽屉 Lint 解析所选模板快照 |

## 11. Markdown → 命名样式（M2）
`backend/office/markdown_to_paragraphs.py` 的 `parse_markdown_document(text)` 返回
`{"paragraphs", "tables", "images"}`；`parse_markdown_to_paragraphs` 保留旧签名（薄封装）。

- 块级：`#`–`###` 标题（行内标记拍平为纯文本）、`-`/`*` 与 `1.` 列表、`> 引用`
  （`style="quote"`）、管道表格（首行表头 + `|---|` 分隔行）、独立 `![alt](src)` 行
  （记入 `after_paragraph` 前一段下标）。
- 行内：`**bold**` → `bold`、`*italic*` → `italic`、`***both***`、`[text](url)` → `link`；
  无标记的段落**不附** `runs` 键，返回结构与历史版本逐键一致。
- 渲染（`word.py`）：`runs` 非空时逐 run 写入——bold → `Strong`、italic → `Emphasis`
  字符样式（参考文档缺该样式时回退直接格式）；link → `w:hyperlink` + 关系 +
  `Hyperlink` 字符样式；`style="quote"` → `Quote` 段落样式（缺失回退默认）。URL 仅
  放行 `http/https/mailto`，其余按纯文本渲染。
- 不处理（YAGNI）：嵌套列表/嵌套强调、转义字符、单元格内 runs。

## 12. 工作区级样式模板（M2）

- 表 `office_style_templates(id, workspace_path, name, format_spec, source_kind,
  source_ref, is_default, created_at, updated_at)`，幂等迁移；仓储
  `style_template_store.py`（list/get/create/delete/set_default，全部工作区限定，
  旧库宽容：表不存在 → 空列表/503）。
- `format_spec` 存**转换后的画像快照**，而非规则包引用——规则包后续修改不静默
  改写已保存模板；`source_kind ∈ {preset, rulepack, manual}` + `source_ref` 溯源。
- 三种保存来源（见 §8）：`format_spec` 原样 / `format_spec_preset` 展开 /
  `rulepack_id`|`pack` 走 `format_spec_from_rulepack` 转换。
- 生成接口**不隐式应用**工作区默认模板（避免改变既有生成结果）；默认只用于前端
  下拉预选。`/style/apply` 与 `/generate` 的合并链：模板 < 预设 < 显式字段
  （None 不覆盖）。

## 13. LLM 工具（M2）

两个工具在 `backend/tools/office_word_intelligence_tools.py`，均
`requires_tool_context = True`（无绑定时不可见，故不进 `_EXPECTED_SCHEMA_NAMES`）：

- `office_style_from_rulepack`（READ）：入参 `{rulepack_id?, rulepack?}`；内联 pack
  优先，否则按 `rulepack_id or DEFAULT_RULEPACK_ID`（`general-quality`）加载 →
  `format_spec_from_rulepack(pack).model_dump()`。
- `office_apply_word_style`（WRITE_LOCAL）：入参 `{file_path, format_spec_preset?,
  style_template_id?, format_spec?, clear_direct_formatting?, dry_run?, overwrite?,
  output_filename?}`；无预设/模板/画像时报错；默认输出 `<stem>-styled.docx`。

注册面（缺一即红）：`OFFICE_TOOLS`（`tool_names.py`）、`TOOL_CAPABILITIES` 与
`_BOUNDARY_SPECS`（`permissions.py`，写工具的 `file_path` 边界）、office_quality
bundle、`tools/__init__._LAZY_TOOL_EXPORTS`、Writer 显式清单、前端
`toolCapabilities.ts`、`test_tool_bundles_parity` golden 计数（122→124 等）。

## 14. 前端入口（M2）

| 入口 | 位置 | 行为 |
|------|------|------|
| 版式下拉 | `GenerateWorkspace`（实际挂载）NL/reference 路径；`OfficeGenerateForm`（未挂载，测试引用） | 内置预设 + 工作区模板；默认模板预选；NL 请求带 `format_spec_preset` / `style_template_id` |
| 样式模板分区 | `TemplateLibrary` 内 `WordStyleTemplateLibrary` | 列表 + 默认徽章 + 删除 / 设默认，数据源 `/style-templates` |
| 套用样式 | `OfficePreviewPanel` Word 工具栏 → `WordStyleApplyDialog` | 预设/模板下拉 + dry-run 预览 + 应用统计，成功后刷新预览 |
| 交付抽屉 Lint | `OfficeDeliveryDrawer` | `formatSpec` 缺失时按 `styleTemplateId` 取模板快照跑 lint / 修复；模板已删 → 如实展示跳过；列表请求失败 → 错误 + 重试 |
| 交付接线 | `GenerateWorkspace` 生成成功后 | word 产物 → `awaiting_approval` + `deliveryRef{formatSpec:null, styleTemplateId}` + 打开抽屉；非 word → `finishTask` |

已知边界：预设（preset）没有公开的 preset → `format_spec` 端点，交付抽屉只能解析
样式模板；选择预设的生成在抽屉里如实显示 lint 跳过。

## 15. win7 同步

一期已同步（PR #3240，2026-11-23），win7 侧技术文档编号为 164；二期（M2）随后
cherry-pick 至 `release/win7`，py38 兼容约束见 §9 末条。
