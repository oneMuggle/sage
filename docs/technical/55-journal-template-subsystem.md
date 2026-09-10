# 55 — Journal Template Article Generation & Validation Subsystem

> 期刊模板文章生成与格式校验子系统（journal/）。本章节是 8-PR 系列的实施追踪文档，按 N1…N8 顺序追加。

## N1 子包骨架（2026-09-10 落地）

- 子包 `backend/office/journal/`：errors / models / pandoc_adapter
- `JournalError` 继承 `OfficeError`，6 个细分错误码稳定
- `JournalSpec` / `JournalContent` / `JournalViolation` / `JournalGenerationRecord` 4 个 Pydantic v2 模型
- `.doc` → `.docx` 经 `pandoc --from doc --to docx` 透明转换，按 sha256 缓存到 `<cache_dir>/<sha256>.docx`
- 4 个 docx fixture：`simple_chinese_template.docx` / `bad_template_corrupt.docx` / `good_filled_paper.docx` / `bad_filled_paper.docx`

## N2 parser + persistence + DB tables（2026-09-10 落地）

- `backend/office/journal/parser.py`：`parse_journal_spec(input_path)` 从 .doc/.docx 抽取 JournalSpec（字体 / 字号 / 行距 / 页边距 / 章节 / 引用风格）
- `backend/office/journal/persistence.py`：`save_spec / load_spec / list_specs / record_generation / list_generations` 全部走 `resolve_within(workspace, ...)` 围栏
- DB tables：`ensure_journal_tables()` 在 `backend/data/database.py` 的 `init_db` 末尾追加一行调用，落盘到工作区 `journal/specs/` 目录（JSON 形态）+ SQLite 索引
- 测试覆盖：`tests/unit/office/journal/test_parser.py`（8） + `tests/integration/office/journal/test_persistence.py`（9）

## N3 validator + 7 类规则（2026-09-10 落地）

- `backend/office/journal/validator.py`：`validate_document(spec, doc)` 依次跑 7 个 `check_*` 函数返回 `List[JournalViolation]`
- 7 类规则：`check_body_font` / `check_heading_font` / `check_body_size` / `check_line_spacing` / `check_margins` / `check_headings` / `check_citations`
- 容差：字体同族别名（`parser._FONT_FAMILY_ALIASES`）、字号 ±0.5pt、页边距 ±0.3cm
- 测试覆盖：`tests/unit/office/journal/test_validator.py`（5）+ fixture-driven bad template 用例

## N4 generator（structured-fill）（2026-09-10 落地）

- `backend/office/journal/generator.py`：`generate_structured(spec, content, workspace, output_filename) → JournalGenerationRecord`
- 实现要点：`_set_eastasia_font` 同时改 Normal style + Character 样式；`sectPr` 跨 body wipe 保留；`record_generation` 先 `save_spec` 防 FK 违反（N4 ruling）
- 拒绝 overwrite：文件名已存在抛 `JournalGenerationError`；调用方（N5 LLM）必须用唯一文件名
- 测试覆盖：`tests/integration/office/journal/test_generator.py`（7）

## N5 LLM generate_article + 2 轮自纠 + LLM adapter（2026-09-10 落地）

- `backend/office/journal/generator.py:generate_article`：第一轮直出，第二轮最多注入 validator 错误做修正
- `backend/office/journal/llm_adapter.py`：`JournalLLMAdapter` 包装 `ProviderClient`，暴露 `(system_prompt, user_prompt, output_schema) → dict` 接口；`get_default_journal_llm_adapter()` 从环境变量/配置解析模型名
- N5 ruling：`generate_article` 必须从 async 上下文调用；同步 tool wrapper 用 `asyncio.run()` 或 `loop.run_until_complete()` + `loop.is_running()` 守卫

## N6 5 个 HTTP 端点 + 4 个 LLM tools + profiles（2026-09-10 落地）

- `backend/api/office_routes.py` 5 个新端点（挂载在 `/api/v1/office/journal/*`）：
  - `POST /journal/parse-template`
  - `GET /journal/specs`
  - `GET /journal/specs/{spec_id}`
  - `POST /journal/fill-from-content`
  - `POST /journal/validate`
- `backend/tools/office_journal_tool.py` 4 个 LLM tool：`OfficeJournalParseTemplateTool` / `OfficeJournalFillFromContentTool` / `OfficeJournalGenerateArticleTool` / `OfficeJournalValidateTool`
- 工具注册：`tool_names.JOURNAL_TOOLS` + `ALL_BUILTIN_TOOL_NAMES` + `profiles.py` writer/primary 种子
- 错误映射：`JournalParseError` 必须传播为 422（N6 fix：保留 `isinstance(OfficeParseError)` 契约）

## N7 frontend JournalPanel + IPC bridge + Vitest（2026-09-10 落地）

- `src/features/journal/`：`JournalPanel` + `useJournalTemplates` hook + 4 组件（`JournalSpecCard` / `JournalContentEditor` / `JournalActions` / `JournalValidationReport`）
- `src/shared/api/journalApi.ts`：`journalApi.parseTemplate/listSpecs/getSpec/validate/fillFromContent`，错误信封走 `handleApiError`
- `electron/preload.ts`：`window.electronAPI.journal.{parseTemplate, listSpecs, getSpec, validate, fillFromContent}`，IPC 通道名 `office_journal_*`
- 挂载点：`src/pages/Office.tsx:495`（`<JournalPanel workspacePath={workspacePath} />`）
- 13 个 Vitest：`useJournalTemplates.test.ts`（5） + `JournalSpecCard.test.tsx`（4） + `JournalValidationReport.test.tsx`（4）；全量 1845/2 skipped/0 failed

## N8 E2E tier-1 + 文档（2026-09-10 落地）

- `tests/e2e/journal.spec.ts`：3 个 hermetic E2E 用例（`addInitScript` 注入 mock，`page.evaluate` 直接调 IPC 通道）：
  - `parseTemplate returns spec shape with body_pt + headings + citation_style`
  - `validate returns error_count > 0 and violation array for bad filled paper`
  - `fillFromContent round-trip returns output_path + generation_id`
- `playwright.config.ts`：注册 `journal-e2e` project，`testMatch: /journal\.spec\.ts$/` 避免与现有 `e2e` project 重复跑
- 5 个 `data-testid` hook（future-friendly，E2E 用例未直接使用）：
  - `JournalSpecCard`：`journal-spec-summary`
  - `JournalValidationReport`：`journal-validation-report`
  - `JournalActions`：`journal-pick-template` / `journal-validate` / `journal-fill`
- 文档：`docs/technical/55-journal-template-subsystem.md` N1–N8 全部追加；`docs/user-manual/13-journal-template-panel.md` 新建；`docs/technical/54-office-parity-tracking.md` 能力矩阵追加 2 行
