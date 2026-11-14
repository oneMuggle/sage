# win7 auto-sync 报告

- 时间：2026-11-14T09:56:53
- source：`origin/main` @ `561092795`
- target：`origin/release/win7` @ `d00f084fa`
- 分支：`sync/win7-main`
- 待并入 commits：**39**
- 状态：**CONFLICT（23 个文件需人工处理）**

## 自动取 ours 的 D 类冲突（发布/打包冻结件）
- `electron-builder.yml`
- `package-lock.json`
- `package.json`

## 需人工处理的冲突

| 文件 | 类别 | 建议 |
|------|------|------|
| `.github/dependency-audit-policy.json` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `architecture-baseline.json` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/api/diagnostic_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/api/office_ai_review_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/data/database.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/design/craft_loader.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/design/lint.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/design/pptx_mapper.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/office/models/_excel.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/office/models/_shared.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/office/models/_word_gen.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/office/pdf_to_word.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/office/word_rule_extract_template.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_chart_embedder.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tools/base.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tools/browser_cdp.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/plans/2026-11-09_startup-performance-optimization.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/plans/2026-11-10_orch-plan-confirm-persistence.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/technical/147-project-workbench-ia.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/technical/README.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/user-manual/README.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/features/office/sidebar/OfficeAiSidebarHost.tsx` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `src/features/office/sidebar/useAiCapabilities.ts` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |

处理步骤：`git checkout sync/win7-main` → 解决冲突 → `python scripts/py38_compat_rewrite.py backend packages/sage-core` → `python scripts/check_py38_compat.py` → 提交。


> 由 `scripts/win7/auto_sync.py` 生成。合并后请跑完整 pytest / vitest，并与 `docs/win7-sync/parity.md` 中的宿主环境性失败清单对照。