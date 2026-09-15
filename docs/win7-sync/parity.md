# Win7/Main Parity 看板 — 2026-09-15

- merge-base: `0643265b02b4c034dabd1cb6118c783f55bd84e5`
- main ahead: **728** / win7 ahead: **499**（基线）
- 异动文件：**1937 → 865 (B1) → 832 (B2) → 235 (B3)**（`git diff --name-only origin/main HEAD`）
- B3 后剩余 235 文件构成：backend/tests 58（win7 专属/断言差异）、docs 33、backend 平台层+py38 重写 ~90、src/electron 12（Memory 3-tab 页 + 类型声明 + backendLauncher D 类）
- 分类（初版）：A=1807 B=121 C=6 D=3

| 维度 | 目标 | 基线 | B1 后 | B3 后 | 差距 |
|------|------|------|-------|-------|------|
| 功能对齐 | >=95% | ~62% | ~72%（Office 100%） | ~93%（main 728 commits 全部并入；win7 独有：记忆可追溯/SSE/auto_memory 保留） | B4-B6 收尾 |
| 代码同源 | >=80% | ~54% | ~58% | ~88%（235/1937 文件仍异，其中 ~150 为 win7 必要差异：compat 层、py38 重写、win7 测试） | B4-B6 |
| 发布同构 | 同构 | 差异 67 文件 (D) | 不变 | 不变（D 类保持 win7） | Phase 3 |
| 约束隔离 | >=90% 集中 | 散弹 | `backend/compat/win7` 建立 | memory/chat/tools 域经 `_run_db_sync` / run_in_executor 替代 `asyncio.to_thread`，pydantic `class Config` 走垫片 | 其余域 |

## 批次进度

| 批次 | 范围 | 状态 | 提交 | 验证 |
|------|------|------|------|------|
| P0/P1 | 骨架 + 分拣 + 平台层 | ✅ | eb801245 | classify.csv |
| B1 | Office R26-30 → **整树同源** | ✅ | 04601360 (后端 93 文件) / 653084b7 (前端 33 文件) | pytest 666 pass / tsc 0 / vitest 590 pass |
| B2 | Wiki/Projects | ✅ | c7c21a99 | pytest 6362 pass / py38 0 violations |
| B3 | Chat/RAG + memory + tools + UI（`git merge --no-ff origin/main`，全量并入） | ✅ | 8d3411d4 | py38 0 violations / pytest 6941 pass, 66 fail 全为 b2/baseline 或宿主环境 / tsc 0 (app+electron) / vitest 2227 pass, 4 fail 与 win7 基线一致（POSIX 路径） |
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

## B3 经验
1. **域级落后 >100 commits 时直接 `git merge --no-ff origin/main`**，只对冲突域做 3 路归并；
   记忆域（20 文件）尝试过 win7 整树保留 → 57 个新失败，改为"main 语义为底 + win7 增量嫁接"后归零。
2. main 的 py3.9+ API 在 win7 分支的替代：`asyncio.to_thread` → `_run_db_sync`/`run_in_executor`；
   `str.removeprefix` → 切片；`zoneinfo` → 保持 win7 实现。`check_py38_compat.py` 作为批次门禁。
3. 语义冲突靠测试仲裁：main 的 dict 返回 vs win7 的 int 契约 → `ConsolidationResult(int)` 双满足；
   WorkingMemory 按 session 隔离后，测试断言从 `working.messages` 改为 `get_context(sid)`。
4. 测试文件同样 3 路归并：main 测试为底，追加 win7 专属断言（可追溯字段、async handler 白名单 +3）。
5. 宿主环境性失败清单（非回归，基线同样失败）：WinError 1314 符号链接、doctor CLI gbk/`O_NONBLOCK`、
   test_hooks_system、test_skill_delete、vitest officePaths/officeIpc/updateManager 的 POSIX 路径断言。

> 由 `scripts/win7/classify_diff.py` + `parity_report.py` 生成；批次表手工维护。
