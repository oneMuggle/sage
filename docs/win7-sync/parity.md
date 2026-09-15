# Win7/Main Parity 看板 — 2026-09-15

- merge-base: `0643265b02b4c034dabd1cb6118c783f55bd84e5`
- main ahead: **728** / win7 ahead: **499**（基线）
- 异动文件：**1937 → 865**（B1 完成后 `git diff --name-only origin/main HEAD`）
- 分类（初版）：A=1807 B=121 C=6 D=3

| 维度 | 目标 | 基线 | B1 后 | 差距 |
|------|------|------|-------|------|
| 功能对齐 | >=95% | ~62% | ~72%（Office 100%） | B2-B6 |
| 代码同源 | >=80% | ~54% | ~58%（office/task-center/ui/i18n 同源） | B2-B6 |
| 发布同构 | 同构 | 差异 67 文件 (D) | 不变 | Phase 3 |
| 约束隔离 | >=90% 集中 | 散弹 | `backend/compat/win7` 建立，office 域 100% 经垫片 | 其余域 |

## 批次进度

| 批次 | 范围 | 状态 | 提交 | 验证 |
|------|------|------|------|------|
| P0/P1 | 骨架 + 分拣 + 平台层 | ✅ | eb801245 | classify.csv |
| B1 | Office R26-30 → **整树同源** | ✅ | 04601360 (后端 93 文件) / 653084b7 (前端 33 文件) | pytest 666 pass / tsc 0 / vitest 590 pass |
| B2 | Wiki/Projects | ⏳ | | |
| B3 | Chat/RAG + session_search/execute_code | ⏳ | | |
| B4 | Orchestration | ⏳ | | |
| B5 | Web-access | ⏳ | | |
| B6 | UI 批次 | ⏳ | | |

## B1 经验（写入后续批次约定）
1. **cherry-pick 只适合 ≤3 commits 的孤立改动**；域级落后 >10 commits 时直接
   `git checkout origin/main -- <subtree>` 再统一跑 py38 重写 + 垫片，成本低一个数量级。
2. Win7 适配三板斧（每批次固定流程）：
   - `python scripts/py38_compat_rewrite.py <paths>` → `check_py38_compat.py` 0 violations
   - v2-only pydantic API 经 `backend.compat.win7.pydantic_compat`（包 `__init__` 顶部 `install()`）
   - `cwd=backend` 跑 pytest（与 CI 一致；`backend/platform` 曾遮蔽 stdlib，已改名 `compat`）
3. 已知环境性失败：`WinError 1314`（符号链接需管理员）2 例，基线同样失败，非回归。
4. 宿主 python：`D:\programmingSoftware\Anaconda3\envs\sage-backend\python.exe`（3.11 + pydantic 2.5）；
   pydantic 1.x 实机验证留给 win7 CI（requirements-py38）。

> 由 `scripts/win7/classify_diff.py` + `parity_report.py` 生成；批次表手工维护。
