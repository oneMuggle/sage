# Word 样式模板 M2：Markdown 命名样式 / 前端 UI / LLM 工具 / 模板持久化

> 状态：实施中（2026-11-23，分支 `feat/word-style-template-m2`，基于 main `dbf87627f`）
> 前置：[161 Word 样式模板](../technical/161-word-style-template.md)（PR #3231 / win7 #3240）

## 1. 背景与目标

样式模板系统一期已落地（按级字体、命名预设、参考文档、规则包→画像、已有文档套用），
技术文档 §11 留下四项未实现能力，本轮 M2 收口：

1. **Markdown 解析升级**——`markdown_to_paragraphs.py` 目前只识别标题/列表/段落，
   `**bold**` / `*italic*` / 链接 / 图片 / 表格 / 引用全部退化为纯文本。升级为
   「映射到命名样式」：加粗/斜体 → Strong/Emphasis 字符样式，链接 → Hyperlink
   字符样式 + 真实超链接，引用 → Quote 段落样式，图片/表格 → 结构化
   images/tables，而非直接格式或丢弃。
2. **前端 UI**——自由创建页「版式」下拉（内置预设 + 工作区样式模板）、模板库
   样式模板分区、已有文档「套用样式」入口、交付抽屉 Lint 使用所选模板。
3. **LLM 工具注册**——`office_style_from_rulepack`（READ）与
   `office_apply_word_style`（WRITE_LOCAL），golden 快照同步。
4. **工作区级样式模板持久化**——复用 `spec_library` 的工作区绑定模型，把
   「规则包/预设 → 样式画像」结果存成可复用模板（`office_style_templates` 表）。

## 2. 涉及文件与模块

### 后端

| 文件 | 改动 |
|------|------|
| `backend/office/markdown_to_paragraphs.py` | 新增 `parse_markdown_document()`（paragraphs/tables/images）；内联 tokenizer（bold/italic/链接）；引用/表格/图片块解析；旧函数保留为薄封装 |
| `backend/office/models/_word_gen.py` | 新增 `WordRunSpec`；`WordParagraphSpec.runs`；`style` Literal 增 `quote` |
| `backend/office/word.py` | runs 渲染分支：Strong/Emphasis 字符样式、Hyperlink 字符样式 + `w:hyperlink`、Quote 段落样式；URL scheme 白名单 |
| `backend/tools/office_create_tool.py` | `_normalize_content` 采用 `parse_markdown_document` 并透传 tables/images；content schema 增 `runs`/`style` 声明 |
| `backend/office/style_template_store.py`（新建） | `office_style_templates` CRUD（仿 `spec_library`） |
| `backend/office/style_template_models.py`（新建） | `OfficeStyleTemplate` / 列表/保存结果模型 |
| `backend/data/database.py` | 幂等迁移：`CREATE TABLE IF NOT EXISTS office_style_templates` |
| `backend/api/office_word_style_routes.py` | `style-templates` CRUD + `from-rulepack` 保存；`style/apply` 支持 `style_template_id` |
| `backend/tools/office_style_from_rulepack_tool.py`（新建） | READ 工具：规则包 → 样式画像 |
| `backend/tools/office_apply_word_style_tool.py`（新建） | WRITE_LOCAL 工具：套用样式到已有文档 |
| `backend/office/tool_service.py` | 受管路径透传 `runs`/`quote`/tables/images（如现有透传有缺口） |
| `architecture-baseline.json` | 增长文件的棘轮基线同步 |

### 前端

| 文件 | 改动 |
|------|------|
| `src/shared/api/types.ts` | `WordRunSpec`、`WordParagraphSpec.runs`、style 联合 + `quote`；`WordStylePreset`/`WordStyleTemplate`/apply/from-rulepack 请求响应类型 |
| `src/shared/api/officeApi.ts` | 新方法 `listWordStylePresets`/`applyWordStyle`/`styleFromRulepack`/`listWordStyleTemplates` 等；`generateWord` 透传 `formatSpecPreset`/`formatSpec`（当前丢弃） |
| `electron/commandRoutes/office.ts` + `electron/ipc-manifest.json` | 新 IPC 命令（`office_word_style_presets` 等），`npm run ipc:manifest` 重生成，`ipc-contract.test.ts` 门禁 |
| `src/features/office/GenerateWorkspace.tsx`（实际挂载的生成 Tab，378 行） | 「版式」下拉（内置预设 + 工作区模板），透传到 NL 生成路径 |
| `src/features/office/OfficeGenerateForm.tsx`（790 行，当前未挂载） | Word 自由创建表单加同款下拉 + `formatSpecPreset` 透传（供测试与未来挂载） |
| `src/features/office/TemplateLibrary.tsx`（115 行） | 「样式模板 / 版式」分区（调 style-presets + style-templates 接口） |
| `src/features/office/WordStyleApplyDialog.tsx`（新建） | 套用样式对话框：模板/预设选择、dry-run 预览、应用 |
| `src/features/office/OfficePreviewPanel.tsx`（848 行） | Word 工具栏「规则审校」旁加「套用样式」按钮并挂载对话框 |
| `src/features/office/OfficeDeliveryDrawer.tsx`（450 行） | Lint 使用所选样式模板解析出的 `format_spec` |
| `src/shared/api/demoOfficeAndSystemHandlers.ts` | 新命令的 demo stub |
| i18n `zh/en/workspaceAndTools.ts`、`settingsAndModels.ts` | 新 UI 文案 |

### 测试与文档

| 文件 | 覆盖 |
|------|------|
| `backend/tests/unit/office/test_markdown_to_paragraphs.py` | 内联样式/引用/表格/图片 |
| `backend/tests/integration/test_office_word_markdown_styles.py`（新建） | runs → 字符样式/超链接/Quote/表格/图片闭环 |
| `backend/tests/unit/tools/test_office_create_schema_contract.py` | paragraphs schema ↔ 模型字段契约扩展 |
| `backend/tests/unit/office/test_style_template_store.py`（新建） | CRUD/工作区隔离 |
| `backend/tests/unit/office/test_word_style_from_rulepack.py` | 模板保存/apply 解析 |
| `backend/tests/unit/tools/test_office_style_tools.py`（新建） | 两个新工具 |
| golden 快照 | 新工具注册后重生成 |
| `docs/technical/161-word-style-template.md` | §11 改写为已实现说明 |

## 3. 技术方案

### 3.1 Markdown → 命名样式

- `parse_markdown_document(text)` → `{"paragraphs": [...], "tables": [...], "images": [...]}`；
  `parse_markdown_to_paragraphs` 保留原签名，返回 paragraphs。
- 内联 tokenizer：`**bold**` → `{"text": ..., "bold": true}`；`*italic*` →
  `{"italic": true}`；`***both***`；`[text](url)` → `{"text": ..., "link": url}`。
  仅当行内出现标记时才附带 `runs` 键（不传时旧测试与行为不变）。
- `> 引用` 块 → `style="quote"`；管道表格（含 `|---|` 分隔行）→
  `{"headers": [...], "rows": [...]}`；独立 `![alt](src)` 行 → `{"source": src,
  "caption": alt, "after_paragraph": 前一段下标}`。
- 标题行内的内联标记拍平为纯文本（标题不做 runs）。
- 渲染（`word.py`）：`runs` 非空时逐 run 写入；bold→`Strong`、italic→`Emphasis`
  字符样式（参考文档缺该样式时回退直接格式）；link→`w:hyperlink` + 关系 +
  `Hyperlink` 字符样式（缺则按需创建）；`style="quote"`→`Quote` 段落样式
  （缺样式时回退默认）。URL 只放行 `http/https/mailto`，其余按纯文本渲染。
- 无 runs / 无新 style 的请求走原路径，保证历史产物逐字节语义不变。

### 3.2 LLM 工具

两个工具加入现有 `backend/tools/office_word_intelligence_tools.py`（复用
`_WordToolBase._guard()/_resolve_pack()`），`requires_tool_context = True`：

- `office_style_from_rulepack`（READ）：入参 `{rulepack_id?, rulepack?}`；inline pack
  优先，否则 `load_rulepack(workspace_root, rulepack_id or DEFAULT_RULEPACK_ID)`
  （默认 `general-quality`）→ `format_spec_from_rulepack(pack).model_dump()`。
- `office_apply_word_style`（WRITE_LOCAL）：入参 `{file_path, format_spec_preset?,
  style_template_id?, format_spec?, clear_direct_formatting?, dry_run?,
  overwrite?, output_filename?}`；无预设/画像时报错；`_enforce_workspace(file_path)`
  → `apply_style_to_document(...)`；默认输出 `<stem>-styled.docx`。

注册面（缺一即红）：

| 位置 | 改动 |
|------|------|
| `backend/domain/tool_names.py` `OFFICE_TOOLS` | 加两个名字（`ALL_BUILTIN_TOOL_NAMES` 自动派生） |
| `backend/tools/permissions.py` `TOOL_CAPABILITIES` | WRITE/READ 各一条；`_BOUNDARY_SPECS` 仅写工具（`file_path`） |
| `backend/tools/tool_bundles.py` | 导入 + `_install_office_quality` 注册（office_quality bundle） |
| `backend/tools/__init__.py` | `_LAZY_TOOL_EXPORTS` + `__all__` |
| `backend/agents/profiles.py` | Writer 显式清单 + `_WRITER_CURRENT_DEFAULT_TOOLS`（Primary 经 `*OFFICE_TOOLS` 自动获得） |
| `src/entities/specialist/toolCapabilities.ts` | office 组 `tools` 列表 |
| `backend/tests/unit/test_tool_bundles_parity.py`（golden，手维护） | `_EXPECTED_ONLINE` 插入两项；计数 122→124、121→123、117→119；`(122,121,117)`→`(124,123,119)` |
| 测试同步 | `test_tool_capabilities`、`test_tool_names`、`test_profiles_office_tools`、`test_specialist_tool_packs_drift`、`test_risk`、`test_office_tool_registration` |

两个工具均 `requires_tool_context=True`，故不进 `_EXPECTED_SCHEMA_NAMES`（无绑定时不可见）。

### 3.3 工作区级样式模板

- 表：`office_style_templates(id, workspace_path, name, format_spec TEXT,
  source_kind, source_ref, is_default, created_at, updated_at)`，幂等迁移。
- 仓储 `style_template_store.py`：`list/get/create/delete/set_default`，全部
  workspace 限定，仿 `spec_library` 的旧库宽容策略（表不存在 → 空列表/503）。
- `format_spec` 存转换后的快照（而非规则包引用），规则包后续修改不静默改写
  已保存模板；`source_kind ∈ {preset, rulepack, manual}` + `source_ref` 溯源。
- 路由：
  - `GET /office/word/style-templates?workspace_path=`
  - `POST /office/word/style-templates`（三种来源：`format_spec` 原样 /
    `format_spec_preset` 展开 / `rulepack_id`|`pack` 走 from-rulepack 转换）
  - `POST /office/word/style-templates/{id}/activate`、`DELETE /office/word/style-templates/default`
  - `DELETE /office/word/style-templates/{id}?workspace_path=`
  - `POST /office/word/style/apply` 增 `style_template_id`（与 preset/format_spec
    深合并链：模板 < 预设 < 显式字段）。
- 生成接口不隐式应用工作区默认模板（避免改变既有生成结果）；默认只用于前端
  下拉预选。

### 3.4 前端

- **两套生成面**：`GenerateWorkspace`（实际挂载，nl/reference/template/iterate 四模式）与
  `OfficeGenerateForm`（构造 `OfficeWordGenerateRequest`，但当前未挂载，仅测试引用）。
  「版式」下拉两处都加：`GenerateWorkspace` 的 NL 路径透传预设；`OfficeGenerateForm`
  的 Word 自由创建字段区加下拉并透传 `format_spec_preset`。
- `officeApi.generateWord` 目前只透传 workspace/filename/title/paragraphs/tables/task_id
  ——需补 `formatSpecPreset`/`formatSpec`/`templateDocxPath`（invoke 层自动 camel→snake）。
- 新 IPC 命令沿用 `commandRoutes/office.ts` 声明式路由 + `npm run ipc:manifest`，
  并由 `electron/__tests__/ipc-contract.test.ts` 强制。
- 套用样式入口：`OfficePreviewPanel` Word 工具栏「规则审校」旁新增按钮，打开
  `WordStyleApplyDialog`（预设/模板下拉 + dry-run 预览 + 应用结果统计）；对话框
  成功后 `onApplied` 刷新预览。
- 交付抽屉 Lint：`OfficeDeliveryDrawer` 已有 `formatSpec` prop；若入口传入样式模板
  id，则在抽屉内先 `from-rulepack`/模板解析再跑 lint（Lint 失败指引不变）。
- 样式模板分区置于 `TemplateLibrary`（文档模板列表上方），复用 `OfficeSpecLibrary`
  的交互形态（列表 + 默认徽章 + 删除），但数据源是 `/word/style-templates`。
- demo 模式补 stub；i18n 中英文案齐备；`OfficePreviewPanel.tsx` 848 行、接近棘轮
  上限，新按钮+挂载点需同步基线。

## 4. 实施步骤

- [x] M-A1 解析器：`parse_markdown_document` + 内联 tokenizer + 引用/表格/图片（TDD）
- [x] M-A2 模型：`WordRunSpec` / `runs` / `quote`
- [x] M-A3 渲染：字符样式/超链接/Quote + 集成测试
- [x] M-A4 工具 content schema 与 `_normalize_content` 透传 + 契约测试扩展
- [x] M-B1 `office_style_from_rulepack` 工具 + 测试
- [x] M-B2 `office_apply_word_style` 工具 + 测试 + golden 快照
- [x] M-C1 `office_style_templates` 迁移 + 仓储 + 测试
- [x] M-C2 路由（CRUD/activate/from-rulepack/apply 集成）+ 测试
- [x] M-D1 前端类型与 API 封装
- [x] M-D2 自由创建页「版式」下拉
- [x] M-D3 模板库「样式模板」分区
- [x] M-D4 已有文档「套用样式」入口
- [x] M-D5 交付抽屉 Lint 使用所选模板
- [x] M-E 文档更新（§11 → 已实现）、架构棘轮基线、ruff/tsc/prettier/pytest 全绿
- [ ] M-F PR + win7 同步

## 5. 风险与依赖

- **OOXML/渲染回归**：runs 渲染只在 `runs` 存在时启用，旧路径零改动；集成测试
  锁定旧产物结构不变。
- **参考文档缺字符样式**：Strong/Emphasis/Quote/Hyperlink 在自定义模板缺失时
  回退直接格式/默认段落样式，不抛错。
- **超链接安全**：仅 http/https/mailto 生成真实链接；javascript:/data: 等按
  纯文本落盘。
- **表/图路径**：Markdown 图片 `src` 按工作区/输出目录解析，解析失败按现有
  插图错误路径报错。
- **棘轮基线**：`word.py`/`office_create_tool.py`/`tool_service.py` 及前端超
  800 行文件需同步 `architecture-baseline.json`。
- **py38/pydantic v1**：新代码沿用 `typing.Optional/List/Dict`、v1/v2 兼容写法。
- **win7 同步**：完成后 cherry-pick 到 release/win7（文档编号 164），门禁同前。
