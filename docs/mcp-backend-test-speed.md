# 后端测试提速：legacy smoke 超时修复与每进程模板库

> 日期: 2026-09-26 ~ 09-27 · 基线: `origin/main` @ `8892da663`（#1631 之前）、`3e8ba5900`（模板库 PR 的基线）
> 相关 PR: main #1631（→ `39e22482f`）、#1640（→ `eaded3bf8`）；release/win7 #1633（→ `f8a48c5c0`）、#1646（→ `2b48abcfc`）
> 范围: `backend/tests/conftest.py` 的逐用例固定开销。只改测试基础设施，不动产品代码。
> 对齐: main 落地 → cherry-pick `release/win7`（见 §5）。

---

## 0. 结论速览（TL;DR）

| 问题 | 结论 |
| --- | --- |
| 症状 | main 上非阻断的 Backend legacy smoke 连续变红（`4a5891e83`、`0dcc6e2d6`）：pytest 步骤撞上 20 min 超时被掐断，不是用例失败；唯一通过的一次（`8892da663`）本步用了 18m44s |
| 根因 | 时间耗在逐用例的固定开销上：autouse `setup_test_db` 每个用例都从空文件跑一遍 `init_db()`（115 条表/索引），`tmp_db_path` 收尾每次都做一次全量 `gc.collect()` |
| 第一步：#1631 | `tmp_db_path` 先直接 `unlink`，只有 `PermissionError` 时才 `gc.collect()`：legacy pytest 1125 s → 266 s，Backend (Python) 1201 s → 310 / 408 s |
| 第二步：模板库 | 每个进程只建一次模板库，逐用例复制后再调用幂等的 `init_db()`：每个用例 33.9 ms → 3.0 ms。CI 上 Backend (Python) pytest 427 s → 275 s、legacy 276 s → 178 s（均 −36%），win7 Python 3.8 384 s → 283 s（−26%），用例结果与覆盖率不变 |
| 更正 | #1631 说明里「每个用例 `init_db()` 146 ms」测量时漏了 `SAGE_TEST_FAST_SQLITE`，实际约 34 ms（§6） |
| 双分支 | 两步都在 main 合并后 cherry-pick 到 `release/win7`：win7 必过的 Backend (Python 3.8, Win7 LTS) 跑的也是整套用例 |

---

## 1. 症状与证据

- `.github/workflows/ci.yml` 的 `backend-legacy` job：`continue-on-error: true`，只在 main/develop 上跑；步骤「Pytest legacy (smoke, no-cov)」设 `timeout-minutes: 20`。
- 失败日志：`The action 'Pytest legacy (smoke, no-cov)' has timed out after 20 minutes.`，被掐断之前没有失败的用例。
- `--durations`：≥1 s 的用例合计只有 237 s，其余时间分摊在 1 万多个用例上，所以要看逐用例的固定开销。

## 2. 根因

### 2.1 逐用例的固定开销

`backend/tests/conftest.py`：

| 位置 | 做的事 |
| --- | --- |
| 文件开头 | `os.environ.setdefault("SAGE_TEST_FAST_SQLITE", "1")`：`backend/data/database.py` 的 `get_connection()` 据此设 `synchronous=OFF` |
| `tmp_db_path` | 每个用例建一个临时库文件，收尾删除（#1631 之前：删除前每次都 `gc.collect()`） |
| autouse `setup_test_db` | `Database(db_path=tmp_db_path)` + `init_db()`（从空文件建 115 条表/索引），再 `AgentRepository().seed_defaults_if_empty()` 写入种子 agent |

### 2.2 `gc.collect()` 的来历

#477（2026-09-07）为 Windows 加的：Repo 层没有显式 close 的 sqlite 连接会占住文件，`unlink` 报 WinError 32；先 `gc.collect()`，让连接对象的终结器释放句柄。Linux 上 `unlink` 不受文件占用影响，这一步纯属开销。

### 2.3 实测

| 每个用例 | 数值 | 环境 |
| --- | --- | --- |
| `gc.collect()` | 134 ms | Windows 本机，导入 `backend.main` 之后 |
| `gc.collect()` | 约 0.3 s | CI worker（堆更大） |
| 从空文件 `init_db()` | 33.9 ms（中位数） | Linux 沙箱，Python 3.11，`SAGE_TEST_FAST_SQLITE=1` |
| 复制模板 + `init_db()` | 3.0 ms（中位数） | 同上 |
| 从空文件 `init_db()` | 46.2 ms（中位数） | Linux 沙箱，Python 3.8，release/win7 |
| 复制模板 + `init_db()` | 5.3 ms（中位数） | 同上 |

## 3. 第一步：#1631 按需 gc

### 3.1 改动

- `backend/tests/conftest.py`：`tmp_db_path` 收尾先直接 `unlink`，只有报 `PermissionError`（Windows 上文件被占用）时才 `gc.collect()` 再删一次。Windows 上的效果不变；Linux 上回到 #477 之前的做法。
- `.github/workflows/ci.yml`：只更新 legacy 步骤注释里的实测时长，`timeout-minutes` 维持 20（第一版曾放宽到 30，CI 数据出来后撤回）。

### 3.2 效果（PR CI，对照 main `8892da663`）

| pytest 步骤 | main | #1631 |
| --- | --- | --- |
| Backend (Python)（含覆盖率） | 1201 s | 310 s / 408 s |
| Backend legacy smoke | 1125 s | 266 s / 265 s |

- #1631 一栏是两轮 CI（`a8496a726`、`93b857df6`），每轮都是 10539 passed / 109 skipped，覆盖率 83.37% → 83.38%。
- 合并后 main（`39e22482f`）全绿：Backend (Python) job 7m56s，legacy job 6m06s，Backend unit (Windows) job 10m54s。
- Windows 本机 `tests/unit/services`（399 个用例，单进程）：120.47 s → 58.95 s，结果一致（398 passed, 1 skipped）。

### 3.3 release/win7：#1633

- `backend-legacy` 只在 main/develop 上跑，所以 `ci.yml` 的改动不带过去，只 cherry-pick conftest（hunk 与 main 相同）。
- win7 必过的 Backend (Python 3.8, Win7 LTS) job：基线 22m23s（`5fb00fb70`：pytest 1155.15 s，10002 passed / 126 skipped，覆盖率 82.13%）→ #1633 的 CI：job 9m40s，pytest 374.02 s（10002 passed / 126 skipped，覆盖率 82.12%）。
- 本机 Python 3.8 环境跑 `tests/unit/services`：358 passed, 1 skipped。

## 4. 第二步：每进程模板库

### 4.1 改动（只动 `backend/tests/conftest.py`）

- 新增 session 级 fixture `template_db_path`：在临时文件里跑一次 `init_db()` 后 `close()`（最后一个连接关闭时 checkpoint，WAL 内容落回主文件），session 结束时删除。xdist 下每个 worker 各有一个 session，互不干扰。
- `setup_test_db`：先 `shutil.copyfile(模板, tmp_db_path)`，再照旧 `Database(...)` + `init_db()`。
- 种子 agent 等其余步骤不变，仍逐用例执行：`upsert()` 会写 `updated_at = 当前毫秒`，放进模板会改变时间戳的语义。
- fixture 名不带下划线前缀：ruff PT005 不允许有返回值的 fixture 以 `_` 开头。

### 4.2 为什么结果不变

- `Database.init_db()` 只有确定性的建表/迁移语句（`CREATE ... IF NOT EXISTS`、由 `PRAGMA table_info` 守卫的迁移、`INSERT OR IGNORE`）：不给实例设属性，不读时间、随机数、环境变量。
- 连接级设置（WAL、`busy_timeout`、`foreign_keys`、测试用的 `synchronous=OFF`）都在 `get_connection()` 里，对复制出的库照样生效。
- 从空文件建出的库和复制出的库，`iterdump()` 都是 127 行，逐行相同。
- 复制后仍然调用 `init_db()`：模板即使因为任何原因不完整，也会被补齐，只是慢一点。

### 4.3 效果

- 每个用例：33.9 ms → 3.0 ms（中位数，Linux，Python 3.11）。
- `tests/unit/services`（399 个用例，单进程）：27.63 s → 20.46 s，结果一致（398 passed, 1 skipped）。
- 全量后端用例（Linux 沙箱，2 核，Python 3.11，单进程分 7 段）：pytest 合计 652.3 s → 423.6 s（−35%，每个用例约省 21.5 ms）。两边逐段结果相同：10519 passed / 110 skipped / 19 failed，共 10648 个，与 CI 收集到的数量一致。这 19 个失败在 main 的 conftest 下完全相同，都是沙箱环境所致（见 §8）。
- 已删除但仍打开的文件（泄漏的连接）两边峰值都是 24 个：#1631 改成按需 gc 之后没有累积。
- Windows 本机（Python 3.11）`tests/unit/services`：58.95 s（#1631 之后）→ 41.26 s，结果一致（398 passed, 1 skipped）。
- #1640 的 CI（对照 main `3e8ba5900`，时间取自 pytest 的汇总行）：Backend (Python)（含覆盖率）427.23 s → 274.71 s（−36%），Backend legacy smoke 276.49 s → 177.67 s（−36%）；两边都是 10539 passed / 109 skipped，覆盖率 83.30% 不变。job 时长：Backend (Python) 6m35s，legacy 4m25s。

## 5. 双分支对齐

| 改动 | main | release/win7 |
| --- | --- | --- |
| 按需 gc | #1631 → `39e22482f` | #1633 → `f8a48c5c0` |
| 模板库 | #1640 → `eaded3bf8` | #1646 → `2b48abcfc` |

- 模板库改动和 #1633 改的是同一文件的相邻位置，所以 win7 要等 #1633 合并后再 cherry-pick。
- win7 的 `setup_test_db` 与 main 相同：cherry-pick 无冲突，结果与 main 的改动逐 hunk 相同（期间 release/win7 合入了 #1642，只改测试文件与 CHANGELOG，没动 conftest）。
- Python 3.8 预验证（Linux 沙箱，release/win7 + #1633，按 `backend/requirements-py38.txt` 锁定依赖）：ruff 0.4.4、`scripts/check_py38_compat.py`、`backend/tools/py38_hazard_scan.py` 全部通过；`iterdump()` 127 行逐行相同；`tests/unit/services` + `tests/api` 共 595 个用例两边都是 594 passed, 1 skipped，`--durations=0` 统计的 setup 段合计 39.2 s → 7.5 s（中位数 50.0 ms → 10.0 ms），call 段 16.4 s / 17.1 s 基本不变。沙箱整体耗时波动大，所以以 setup 段为准。
- Windows 本机（Python 3.8.20）：同样三项静态检查通过；`tests/unit/services` 68.52 s（#1633 之后）→ 40.88 s，结果一致（358 passed, 1 skipped）。
- #1646 的 CI（对照 release/win7 `f65dd89cb` 的 push）：Backend (Python 3.8, Win7 LTS) 的 pytest 383.95 s → 282.54 s（−26%）；两边都是 10002 passed / 126 skipped，覆盖率 82.04% 不变；job 8m23s（#1633 为 9m40s）。

## 6. 更正记录

| 日期 | 位置 | 原文 | 更正 |
| --- | --- | --- | --- |
| 2026-09-27 | #1631 说明「原因」一节 | 每个用例 `init_db()` 146 ms | 测量脚本没设 `SAGE_TEST_FAST_SQLITE`，数字含 fsync；按测试的实际配置约 34 ms（Linux 中位数 33.9 ms）。`gc.collect()` 134 ms 与 CI 前后对比不受影响。#1631 的说明已补充更正 |

## 7. 验证矩阵

| 项目 | 方式 | 结果 |
| --- | --- | --- |
| 静态检查 | ruff 0.4.4（与 CI 一致）`ruff check backend/` | 通过（沙箱与宿主机的 Python 3.11 / 3.8 环境都是 0.4.4） |
| 库内容等价 | 从空文件建库 vs 复制模板，比较 `iterdump()` | 127 行，逐行相同 |
| 子集（沙箱） | `tests/unit/services`，单进程，Python 3.11 | 398 passed, 1 skipped（前后一致） |
| 全量（沙箱） | 单进程分 7 段，main 与本改动各跑一遍 | 10519 passed / 110 skipped / 19 failed（前后一致） |
| win7 预验证 | Python 3.8，`tests/unit/services` + `tests/api` | 594 passed, 1 skipped（前后一致），setup 段 39.2 s → 7.5 s |
| Windows 本机 | `tests/unit/services`，Python 3.11 / 3.8 | 398 passed, 1 skipped / 358 passed, 1 skipped（前后一致） |
| main CI | #1640 | pytest 427.23 s → 274.71 s，legacy 276.49 s → 177.67 s；10539 passed / 109 skipped，覆盖率 83.30%（前后一致） |
| win7 CI | #1646 | Python 3.8 pytest 383.95 s → 282.54 s；10002 passed / 126 skipped，覆盖率 82.04%（前后一致） |

## 8. 复现注意事项（Linux 沙箱）

- `/tmp` 如果是内存盘（tmpfs），全量用例会遇到 ENOSPC 和内存紧张：把 `TMPDIR` 指到磁盘上的目录。
- 沙箱里固定有 19 个失败，与本改动无关：临时目录路径含隐藏目录、稀疏检出缺前端文件、没有真实浏览器。
- 2 GB 内存跑 `-n 2` 会被 OOM 杀掉：改为单进程分段跑。

## 9. 进度日志（每完成一步即回填，时间为 UTC+8）

| 时间 | 步骤 | 结果 |
| --- | --- | --- |
| 2026-09-26 | 诊断 legacy smoke 超时 | 20 min 超时、无失败用例；主因是逐用例的 `gc.collect()` |
| 2026-09-26 18:44 | #1631 合并到 main | `39e22482f`，合并后 main 全绿 |
| 2026-09-26 | #1633 CI（release/win7） | 全绿，Backend (Python 3.8, Win7 LTS) 9m40s |
| 2026-09-26 | 模板库沙箱验证 | 全量 652.3 s → 423.6 s，结果一致 |
| 2026-09-26 22:37 | 模板库 win7 版 Python 3.8 预验证 | 静态检查通过；595 个用例结果一致，setup 段 39.2 s → 7.5 s |
| 2026-09-26 23:23 | #1633 合并到 release/win7 | `f8a48c5c0` |
| 2026-09-26 23:57 | 模板库 PR 合并到 main | #1640 → `eaded3bf8`（CI：pytest −36%，结果不变） |
| 2026-09-27 00:12 | 模板库 PR 合并到 release/win7 | #1646 → `2b48abcfc`（CI：Python 3.8 pytest −26%，结果不变） |
| 2026-09-27 00:13 | #1631 说明补充更正 | 146 ms 划掉，文末加「更正」一节并引用 #1640 |
| 2026-09-27 00:13 | 清理实施用的分支与工作树 | #1633、#1640、#1646 的工作树、本地与远程分支和宿主机临时文件均已删除 |

## 10. 参考

- `backend/tests/conftest.py`：`tmp_db_path`、`template_db_path`、`setup_test_db`
- `backend/data/database.py`：`Database.get_connection()`、`Database.init_db()`
- `.github/workflows/ci.yml`：`backend-legacy` job
- PR：#477、#1631、#1633、#1640、#1646
