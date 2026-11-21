# win7 auto-sync 报告

- 时间：2026-11-21T15:05:42
- source：`origin/main` @ `c8e9d2f39`
- target：`origin/release/win7` @ `8275cdfbb`
- 分支：`sync/win7-main`
- 待并入 commits：**102**
- 状态：**CONFLICT（62 个文件需人工处理）**

## 自动取 ours 的 D 类冲突（发布/打包冻结件）
- `electron-builder.yml`
- `package-lock.json`
- `package.json`

## 需人工处理的冲突

| 文件 | 类别 | 建议 |
|------|------|------|
| `.github/dependency-audit-policy.json` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `architecture-baseline.json` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/adapters/out/memory/adapter.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/api/chat_attachment_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/diagnostic_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/legacy_memory_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/office_ai_review_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/v1/design_resources_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/v1/design_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/workspace_preview_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/data/database.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/design/craft_loader.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/design/design_studio.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/design/lint.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/design/messages_store.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/design/pptx_mapper.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/design/tweaks_store.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/main.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/memory/episodic.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/memory/extractor.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/memory/manager.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/model_catalog/schemas.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/office/excel_recalc.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/office/models/__init__.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/office/models/_excel.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/office/models/_shared.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/office/models/_word_gen.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/office/models/_word_read.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/office/pdf_to_word.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/office/ppt.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/office/word_rule_extract_template.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/orchestration/llm_factory.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/scheduler/evolution.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/integration/test_asr_api.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/integration/test_evolution_run_api.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/memory/test_migration.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/test_preference_injection.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/office/test_word_rule_extract.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_agent_step_done.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_browser_account_service.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_chart_embedder.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_memory_adapter.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_r39_pdf_docx_extract.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_tool_bundles_parity.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tools/__init__.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tools/base.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tools/browser_cdp.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/README.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/plans/2026-11-15_pdf-figure-citation.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/plans/2026-11-17_controlled-browser-use.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/plans/2026-11-21_agent-orchestration-parity-upgrade.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/technical/116-local-ocr.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/technical/131-attachment-pipeline.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/technical/147-project-workbench-ia.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/technical/README.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/user-manual/README.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `scripts/check-bundle-size.mjs` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `scripts/check_dependency_audit.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/features/office/sidebar/OfficeAiSidebarHost.tsx` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/features/office/sidebar/useAiCapabilities.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/widgets/chat/progress/TaskDetailView.tsx` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/widgets/chat/progress/__tests__/TaskDetailView.test.tsx` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |

处理步骤：`git checkout sync/win7-main` → 解决冲突 → `python scripts/py38_compat_rewrite.py backend packages/sage-core` → `python scripts/check_py38_compat.py` → 提交。


> 由 `scripts/win7/auto_sync.py` 生成。合并后请跑完整 pytest / vitest，并与 `docs/win7-sync/parity.md` 中的宿主环境性失败清单对照。