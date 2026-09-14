# main ↔ release/win7 最大化对齐方案（实施版）

> 本文件为 worktree `chore/win7-main-sync` 的实施索引，完整可视化报告见根目录 `win7-main-sync-plan.html`

## 基线
- merge-base: `0643265b02b4c034dabd1cb6118c783f55bd84e5`
- main ahead 728 / win7 ahead 499 / 异动 1937 文件
- 约束：Electron 21.4.4 / Python 3.8 / pydantic 1.10.13 / EOL 2027-12-13

## 已落地（Phase 0）
- [x] worktree `chore/win7-main-sync` @ 8776/1431
- [x] `backend/platform/win7/*` 骨架
- [x] `scripts/win7/classify_diff.py` + `parity_report.py`
- [x] `docs/win7-sync/*`

## 下一步（Phase 1 → Phase 2 B1）
见 `win7-main-sync-plan.html` §5-6
