# win7 auto-sync 报告

- 时间：2026-11-09T08:39:26
- source：`origin/main` @ `802c01494`
- target：`origin/release/win7` @ `eefeae0ed`
- 分支：`sync/win7-main`
- 待并入 commits：**19**
- 状态：**CONFLICT（39 个文件需人工处理）**

## 自动取 ours 的 D 类冲突（发布/打包冻结件）
- `electron-builder.yml`
- `package-lock.json`
- `package.json`

## 需人工处理的冲突

| 文件 | 类别 | 建议 |
|------|------|------|
| `architecture-baseline.json` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/api/legacy_memory_feedback_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/legacy_memory_quality_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/legacy_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/office_generate_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/rules_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/data/migrations/runner.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/data/settings_canonicalizer.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/memory/conflict.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/memory/episodic.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/memory/extractor.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/memory/quality_scorer.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/office/models.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/scheduler/evolution.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/services/sage_docs/paths.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/integration/test_memory_feedback_routes.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/integration/test_memory_quality_enrichment.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/integration/test_office_generate_routes.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/test_preference_injection.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_legacy_routes_async_safety.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_memory_consolidation.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_preference_learning_llm.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_schema_migrations.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/plans/2026-11-06_win7-intranet-rescue-doctor.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/plans/2026-11-08_recap-feature.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/technical/README.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/user-manual/45-win7-rescue-tool.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/user-manual/README.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `electron/__tests__/runtime-check.test.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `electron/__tests__/showStartupFailureDialog.test.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `electron/commandRoutes/memory.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `electron/runtime-check.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `electron/showStartupFailureDialog.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/features/rules/__tests__/AiRulePatchDrawer.test.tsx` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/features/rules/useAiRulePatch.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/pages/Memory.tsx` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/shared/lib/i18n/locales/en/rules.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/shared/lib/i18n/locales/zh/rules.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/widgets/chat/RecapCard.tsx` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |

处理步骤：`git checkout sync/win7-main` → 解决冲突 → `python scripts/py38_compat_rewrite.py backend packages/sage-core` → `python scripts/check_py38_compat.py` → 提交。


> 由 `scripts/win7/auto_sync.py` 生成。合并后请跑完整 pytest / vitest，并与 `docs/win7-sync/parity.md` 中的宿主环境性失败清单对照。