# win7 auto-sync 报告

- 时间：2026-11-10T01:32:02
- source：`origin/main` @ `d7b4be85`
- target：`origin/release/win7` @ `bcc35043`
- 分支：`sync/win7-main`
- 待并入 commits：**3**
- 状态：**CONFLICT（3 个文件需人工处理）**

## 需人工处理的冲突

| 文件 | 类别 | 建议 |
|------|------|------|
| `architecture-baseline.json` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |
| `backend/data/database.py` | B | 垫片：优先改 backend/compat/win7，不要改业务文件 |
| `backend/tools/__init__.py` | A | 直通：通常是双方都改了同一行，按 main 语义为底、win7 增量嫁接 |

处理步骤：`git checkout sync/win7-main` → 解决冲突 → `python scripts/py38_compat_rewrite.py backend packages/sage-core` → `python scripts/check_py38_compat.py` → 提交。


> 由 `scripts/win7/auto_sync.py` 生成。合并后请跑完整 pytest / vitest，并与 `docs/win7-sync/parity.md` 中的宿主环境性失败清单对照。