# win7 auto-sync 报告

- 时间：2026-11-28T13:01:40
- source：`origin/main` @ `11ca137ce`
- target：`origin/release/win7` @ `833a1ccfb`
- 分支：`sync/win7-main`
- 待并入 commits：**4**
- 状态：**CONFLICT（9 个文件需人工处理）**

## 需人工处理的冲突

| 文件 | 类别 | 建议 |
|------|------|------|
| `architecture-baseline.json` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/api/presentation_routes.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/services/ppt_master_adapter.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/presentation/test_ppt_master_adapter.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/presentation/test_ppt_master_real_smoke.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tests/unit/test_http_site_gate.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/tools/http_site_gate.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/technical/README.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `docs/user-manual/README.md` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |

处理步骤：`git checkout sync/win7-main` → 解决冲突 → `python scripts/py38_compat_rewrite.py backend packages/sage-core` → `python scripts/check_py38_compat.py` → 提交。


> 由 `scripts/win7/auto_sync.py` 生成。合并后请跑完整 pytest / vitest，并与 `docs/win7-sync/parity.md` 中的宿主环境性失败清单对照。