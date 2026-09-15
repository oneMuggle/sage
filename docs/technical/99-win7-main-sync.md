# main ↔ release/win7 最大化对齐方案（实施版）

> 本文件为 worktree `chore/win7-main-sync` 的实施索引，完整可视化报告见根目录 `win7-main-sync-plan.html`；
> 操作手册与看板见 `docs/win7-sync/README.md` / `parity.md`

## 基线
- merge-base: `0643265b02b4c034dabd1cb6118c783f55bd84e5`
- main ahead 728 / win7 ahead 499 / 异动 1937 文件
- 约束：Electron 21.4.4 / Python 3.8 / pydantic 1.10.13 / EOL 2027-12-13

## 已落地
- [x] Phase 0/1：worktree `chore/win7-main-sync` @ 8776/1431、`backend/compat/win7/*`、`scripts/win7/classify_diff.py` + `parity_report.py`、`docs/win7-sync/*`（eb801245）
- [x] B1 Office 整树同源（04601360 / 653084b7 / 8257b5e8）
- [x] B2 Wiki/Projects（c7c21a99）
- [x] B3 Chat/RAG + memory + tools + UI —— `git merge --no-ff origin/main` 全量并入（8d3411d4）
- [x] B4 Orchestration / B5 Web-access / B6 UI-electron —— 残差审计 + 死代码清理（8cb42cbe）
- [x] Phase 3 自动化：`scripts/win7/auto_sync.py`、`parity_report.py` 六级分级守门、`parity-allow.txt` 台账、`.github/workflows/win7-sync.yml`（52d93474）
- [x] PR #850 CI（真 Python 3.8）回归修复：`asyncio.to_thread` 垫片 `backend/compat/win7/asyncio_compat.py`、`with (` 改写并入 `py38_compat_rewrite.py`、`check_py38_compat.py` 增加运行时 API 第二层门禁（含 tests）、9 类 3.9+/3.10+/3.11+ API 调用点收口（明细见 `docs/win7-sync/README.md`「py38 运行时门禁」）

## 结果
- 异动文件 1937 → 865 → 832 → 235 → **226**，全部为 win7 必要差异（typing-only 87 / frozen 15 / intentional 128）
- main 未并入 commits：**0**
- 后续 main 增量由 `win7-sync.yml` 每日自动 merge → PR；漂移由 `parity_report.py --fail-on` 守门

## 合入与归档
- PR：`chore/win7-main-sync` → `release/win7`，由 `ci.yml` 的 `backend-py38`（真实 Python 3.8）做最终验证
- EOL 2027-12-13：停用 `win7-sync.yml` schedule，打最终 `v*-win7` tag，分支只读归档（见 README 归档预案）
