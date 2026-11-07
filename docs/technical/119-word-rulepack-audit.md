# 119 — Word 规则包、确定性审校与修复（M2a/M2b）

> 日期：2026-11-01 · 分支：`feat/word-rulepack-audit`
> 方案：`docs/plans/2026-10-31_word-document-intelligence.md`（M2）、`docs/plans/2026-11-01_word-rulepack-audit-m2a.md`

## 1. 定位

M2a 把“规范 → 规则 → 审校”中的确定性部分落地：

- `RulePack` / `Rule` 数据模型与三层存储（内置、工作区、请求内联）；
- 15 类确定性检查器，覆盖页面、样式、结构、内容（含 M4a 语义子集）；
- 每条 issue 带 `scope` 与可选 `anchor`（`WordTextAnchor`），为 M2c 前端定位/高亮提供链路；
- 内置两个规则包：GB/T 9704 通用版面参数、Word 通用质量检查。

本阶段**只读**：不修改文档、不执行修复。旧 `/office/word/lint`、`/office/word/repair`
契约与行为不变。

## 2. 规则包模型

```json
{
  "id": "general-quality",
  "name": "Word 通用质量检查",
  "version": "1.0",
  "description": "…",
  "source": null,
  "rules": [
    {
      "id": "content/placeholder_residue",
      "title": "无未解析占位符",
      "category": "content",
      "severity": "error",
      "kind": "content.placeholder_residue",
      "params": {},
      "source": "",
      "fixable": false,
      "fix_hint": "解析或删除 {{}} / <<>> / [[ ]] / 【】 / 交叉引用占位符"
    }
  ]
}
```

- `kind` 选择检查器；未知 kind 在审校/保存前返回 422；
- 规则 id 在包内唯一；单包最多 500 条规则；
- `source` 用于标注标准/范本来源；内置 GB/T 9704 包只收录通用参数，不复制标准全文。

## 3. 存储

| 层 | 位置 | 说明 |
|---|---|---|
| 内置 | `backend/office/word_rulepack_builtin.py` | 只读；id 不可覆盖/删除 |
| 工作区 | `<workspace>/.sage/word-rulepacks/<id>.json` | 记录 `{version, pack, updated_at}`；原子写入；256 KiB 上限 |
| 内联 | 审校请求 `rulepack` 字段 | 即时校验，不落盘 |

加载顺序：工作区同名包优先于内置包；保存时禁止使用内置 id。

## 4. 检查器

| kind | 参数 | 作用 | issue scope |
|---|---|---|---|
| `page.size` | `size` | A4/Letter 纸张 | section |
| `page.orientation` | `orientation` | 纵向/横向 | section |
| `page.margins` | `top_cm/bottom_cm/left_cm/right_cm/tolerance_cm` | 页边距 | section |
| `page.page_number` | `required/format` | 页码域与页码格式 | section |
| `style.font` | `style/font_ascii/font_east_asia/size_pt/bold/italic/underline/color/tolerance_pt` | 样式字体 | style（锚定首个使用段落） |
| `style.paragraph` | `style/line_spacing/line_spacing_pt/first_line_indent_cm/alignment/tolerance_cm` | 样式段落格式 | style |
| `structure.heading_sequence` | `levels/require_prefix/skip_texts` | 多级标题编号连续 | paragraph |
| `structure.required_headings` | `headings/match` | 必含标题/章节 | document |
| `content.placeholder_residue` | — | `{{}}`/`<<>>`/`[[ ]]`/`【】`/交叉引用残渍 | paragraph；内容控件内为 document |
| `content.empty_paragraphs` | `max_consecutive` | 连续空段落超限 | paragraph |
| `content.caption_sequence` | `labels` | 图/表题注编号连续 | paragraph |
| `content.citation_coverage` | — | 引用编号缺号 | paragraph |
| `content.date_format` | `allowed?: cn/iso/slash/dot` | 日期格式一致性（默认主导格式） | paragraph |
| `content.terminology` | `pairs: [{preferred, variants}]` | 术语统一（variant → preferred） | paragraph |
| `content.required_phrases` | `phrases`, `match?` | 必备表述缺失 | document |

容差：页面尺寸 A4 ±1mm、Letter ±0.5mm；尺寸类默认 ±0.05cm；字号默认 ±0.01pt。

## 5. 接口

### 5.1 规则包

```http
GET    /api/v1/office/word/rulepacks?workspace_path=/ws
GET    /api/v1/office/word/rulepacks/gb-t-9704-general?workspace_path=/ws
POST   /api/v1/office/word/rulepacks
DELETE /api/v1/office/word/rulepacks/<id>?workspace_path=/ws
```

列表响应：

```json
{
  "ok": true,
  "workspace_path": "/ws",
  "packs": [
    {"id": "gb-t-9704-general", "name": "…", "version": "1.0", "origin": "builtin", "rule_count": 5},
    {"id": "ws-pack", "name": "…", "version": "1.0", "origin": "workspace", "rule_count": 1}
  ],
  "warnings": []
}
```

保存请求：

```json
{"workspace_path": "/ws", "pack": {"id": "ws-pack", "name": "…", "rules": [...]}}
```

### 5.2 审校

```http
POST /api/v1/office/word/audit
```

```json
{
  "workspace_path": "/ws",
  "file_path": "/ws/doc.docx",
  "rulepack_id": "gb-t-9704-general",
  "rulepack": null,
  "max_size_bytes": 52428800
}
```

`rulepack`（内联）优先于 `rulepack_id`；两者都缺省时使用 `general-quality`。

响应：

```json
{
  "ok": false,
  "source_path": "doc.docx",
  "rule_pack_id": "gb-t-9704-general",
  "rule_pack_name": "…",
  "summary": {"rules_checked": 5, "issue_count": 3, "error_count": 3, "warning_count": 0, "paragraphs": 12, "tables": 0, "sections": 1},
  "issues": [
    {
      "rule_id": "style/body_font",
      "rule_pack_id": "gb-t-9704-general",
      "category": "style",
      "severity": "error",
      "scope": "style",
      "message": "样式 Normal 的中文字体实测 未设置，期望 仿宋_GB2312",
      "expected": "仿宋_GB2312",
      "actual": "未设置",
      "fix_hint": "正文样式改为仿宋_GB2312 三号（16pt）",
      "fixable": true,
      "source": "GB/T 9704-2012（通用版面参数摘要，不复制标准全文）",
      "anchor": {"part": "word/document.xml", "paragraph_index": 0, "run_index": null, "char_start": 0, "char_end": 4, "text_hash": "…", "table_index": null, "row": null, "col": null}
    }
  ],
  "warnings": []
}
```

`ok` = 无 `error` 级 issue。问题数超过 1000 条时截断并追加 `issues_truncated` warning。

### 5.3 确定性修复（M2b）

```http
POST /api/v1/office/word/audit/fix
```

```json
{
  "workspace_path": "/ws",
  "file_path": "/ws/doc.docx",
  "rulepack_id": "gb-t-9704-general",
  "output_filename": "doc-fixed.docx",
  "overwrite": false
}
```

- `overwrite=false`（默认）：输出 `output_filename`（缺省 `<stem>-fixed.docx`），拒绝覆盖源文件或已有文件；
- `overwrite=true`：临时文件 + 原子替换源文件；此时不能同时给 `output_filename`；
- 仅执行 `fixable=true` 且已实现修复器的规则：`page.size` / `page.orientation` / `page.margins` / `page.page_number` / `style.font` / `style.paragraph` / `content.empty_paragraphs`；
- 其他 `fixable=true` 但无修复器的 kind → `fix_unsupported_kind` warning，不写文档；
- 修复后用同一规则包复检，`remaining` 为完整 `WordAuditResult`；`ok` = 复检无 error；
- 幂等：已修复文档再次修复时 `fixed_count=0`、`actions=[]`。

响应字段：`ok` / `source_path` / `output_path` / `overwritten` / `rule_pack_id` /
`actions[{rule_id,kind,fixed_count,message}]` / `fixed_count` / `before` / `remaining` / `warnings`。

### 5.4 原生修订写入（M4b）

```http
POST /api/v1/office/word/audit/revise
```

请求可选 `changes`（显式修订项）；省略时由服务端根据规则包审校结果生成计划：

- `content.terminology`：`variant → preferred`；
- `content.date_format`：实际日期样本转换为期望格式；
- 仅处理 `fixable=true` 的规则与 issue；无可用计划返回 422。

写入规则：

- 定位首个包含 `find` 的正文/表格段落，按字符偏移切分 run；
- 旧文本写入 `w:del`（`w:delText`），新文本写入 `w:ins`（`w:t`），带 `author`/`date`/唯一 id；
- 保留首个受影响 run 的 `rPr`；`\n` 转为 `w:br`；
- 可选在替换前为段落添加批注（复用 comments part）；批注失败仅 warning；
- 默认输出 `<stem>-revised.docx`，`overwrite=true` 时原子替换；修订后用同一规则包复检并返回 `remaining`。

已知限制：`python-docx` 的 `paragraph.text` 不包含 `w:ins` 文本与 `w:delText`，
结构化预览/复检看不到待接受的新文本（Word/WPS 打开可见）；仅支持段落直接普通 run，
批注锚定整段。

## 6. 定位语义

| scope | anchor |
|---|---|
| `paragraph` | 对应段落锚点（段落索引 + 字符范围 + text_hash） |
| `style` | 该样式的首个使用段落锚点；无使用段落时为 null |
| `section` / `document` | null（页面/文档级问题） |

M2c 前端可按 `anchor.paragraph_index` 滚动定位并高亮；`text_hash` 用于文档变更后的弱校验。

## 7. 前端接入（M2c）

`/office` 页 Word 预览工具栏新增「规则审校」开关，挂载 `DocumentAuditPanel`：

- 规则包下拉（内置 + 工作区），切换后自动重跑；
- 审校结果展示错误/警告计数与 issue 卡片（规则 id、期望/实测、来源、修复建议）；
- 按严重级别过滤；
- 点击带 `anchor.paragraph_index` 的 issue → 关闭高保真视图，`WordPreview` 滚动到对应段落并高亮；
  锚点超出 300 段渲染窗口时自动扩展窗口；
- 「一键修复」默认输出 `<stem>-fixed.docx`，勾选「覆盖原文件」时原子覆盖并触发重新读取；
  展示 `fixed_count`、输出路径、复检计数与逐规则修复数；
- 「生成修订」按当前规则包自动派生 tracked changes（术语/日期），可开关批注；
  展示 `applied/skipped`、输出路径、逐条 `find → replace` 与复检计数（M4c）。

IPC 命令：`office_word_rulepacks_list` / `office_word_rulepack_get` /
`office_word_audit` / `office_word_audit_fix` / `office_word_revise`
（manifest 由 `npm run ipc:manifest` 生成）。audit/fix/revise 使用 `rawBody`，
避免规则 `params` 的用户键被 camelCase 改写。

## 8. 限制（后续）

- 表格/内容控件级规则、`vMerge` 跨行内容检查；
- 原生 docx 渲染视图（docx-preview）中的段落定位（DOM 无稳定段落索引）；
- 标题编号/题注/引用的自动重排（当前只在审校中报告，不自动修复）；
- 语义规则已有确定性子集（日期格式/术语表/必备表述）；LLM 语义判断与语义修订（M4）；
- 原生修订已支持（M4b）；修订生成入口已接入审校面板（M4c）；修订 diff/逐条接受拒绝 UI 待后续；
- 修订只处理段落直接普通 run；超链接/域/表格结构级修订待后续；
- 确定性规范/范本规则抽取见 [120](./120-word-rule-extraction.md)；
- 渲染级校验（页边距/字体/页码/页面尺寸）见 [121](./121-word-render-audit.md)。
- 内置 GB 包字体名使用常见实现值（`仿宋_GB2312`），字库差异可通过自定义包覆盖。

## 9. 测试

- `backend/tests/unit/office/test_word_rulepack_audit.py`（9）：内置包校验、干净文档通过、
  页面/样式问题与锚点、标题编号与必含标题、占位符/空段落、题注/引用、样式段落格式、
  未知 kind/重复 id/坏参数、工作区包 CRUD 与内置保护；
- `backend/tests/integration/test_office_word_audit_routes.py`（3）：列表/详情/审校、
  工作区包保存/加载/删除、缺包/坏 kind/超限/越界拒绝；
- `backend/tests/unit/office/test_word_rulepack_fix.py`（9）：内置可修复 kind 覆盖、
  GB 包修复输出、覆盖模式幂等、空段落删除、样式段落修复、不可修复项保留、
  未实现修复器 warning、输出安全、缺文件拒绝；
- `backend/tests/integration/test_office_word_fix_routes.py`（3）：修复端点输出、
  覆盖幂等、缺包/超限/越界/冲突拒绝；
- `src/features/office/__tests__/DocumentAuditPanel.test.tsx`（8）：自动审校/过滤/定位回调、
  规则包切换重跑、默认输出修复、覆盖修复通知父级、错误展示、默认文件名、
  生成修订 applied/skipped、批注开关；
- `src/features/office/__tests__/WordPreview.highlight.test.tsx`（3）：默认不干扰、
  锚点高亮/滚动、超出渲染窗口自动扩展；
- `backend/tests/unit/office/test_word_semantic_rules.py`（6）：日期主导/允许格式、
  术语 variant 锚点、必备表述、参数校验、内置日期规则；
- `backend/tests/unit/office/test_word_revision_writer.py`（7）：tracked replace/批注、
  跨 run 替换、缺文本/重复跳过、覆盖幂等、计划生成、输出安全；
- `backend/tests/integration/test_office_word_revise_route.py`（4）：审校派生计划、
  显式 changes、无计划拒绝、超限/越界拒绝；
- ruff 0.4.4、py38 兼容检查、architecture 门禁、tsc、ESLint、Vitest 通过。
