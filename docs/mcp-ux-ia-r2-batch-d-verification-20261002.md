# UX-IA Round 2 · 批次 D 核查记录（2026-10-02）

> 只读核查 + 本机实跑，未修改任何业务代码。
> 被核查文档：`docs/plans/2026-09-30_ux-ia-round2-batch-d.md`（预算收尾：相关度截断 / hex 接入 / 自动激活技能标记）。
> 基线：`origin/main` @ `38c5f7992`（本地最后一次 fetch）。

## 1. 结论

| 项 | 结论 |
| --- | --- |
| 编码任务（原文 §2 三项） | 全部已落地并双轨合并，**无待实现项** |
| 自动化验证 | 批次 D 专项 6/6 通过；`tests/unit/chat` + `tests/unit/api` 共 623 passed / 1 skipped |
| 仍待人工 | 原文 §4「在运行中的 app 里实测」，清单见 §5 |
| 可选后续 | 相关度打分升级（原文 §4，条件性，不属于批次 D 范围），见 §6 |

## 2. 交付核对

| 原文 §2 | 落点 | 证据 |
| --- | --- | --- |
| 按相关度截断：`apply_context_budget` 新增 `query`，按字符二元组重合度排序，无相关条目时回退到保留开头 | `backend/chat/context_budget.py`（`_truncate_by_relevance`） | main / win7 均命中；3 个用例：相关条目在末尾仍保留、无 query 回退、无相关条目回退 |
| hex 路径接入：`ChatService` 新增 `context_window_resolver` | `backend/application/services/chat_service.py:318`、`:600-608`；`backend/main.py:294-303` | main / win7 各命中 8 处；`test_chat_service_budget_hook`、`test_main_wires_resolver` |
| legacy 路径把本轮输入传给预算器 | `backend/api/legacy_routes.py:1532`（第 4 个参数 `data.message`） | 调用点核对 |
| 标记补全：`skills_activated` 成为独立来源 | `backend/chat/context_sources.py:48`、`:61`；`backend/chat/context_budget.py:44`（截断顺序）；`src/widgets/chat/ContextMeter.tsx:237`（标签「自动激活的技能」） | main / win7 各命中 4 处；`test_hex_memory_prefix_and_activated_skills_are_recognised` |

提交与合并：

| 轨 | PR | 提交 | 合并时间（UTC） | CI |
| --- | --- | --- | --- | --- |
| main | #1864 | `94d54de60` | 2026-09-30 16:22 | All Checks = SUCCESS（Backend、Backend collect (Python 3.8)、Frontend、Architecture check、Electron build ×2、Electron smoke、live-boot 均 SUCCESS；Backend (Python 3.8, Win7 LTS) 与 Backend unit (Windows, non-blocking) 为 SKIPPED） |
| win7 | #1865 | `0238bb43d` | 2026-09-30 16:48 | All Checks = SUCCESS（含 Backend (Python 3.8, Win7 LTS)；Backend (Python)、Backend legacy smoke、Dependency audit 为 SKIPPED） |

#1864 共改 9 个文件（+204 / −5）：`architecture-baseline.json`、`backend/api/legacy_routes.py`、`backend/application/services/chat_service.py`、`backend/chat/context_budget.py`、`backend/chat/context_sources.py`、`backend/main.py`、`backend/tests/unit/chat/test_context_budget_r2d.py`、`docs/plans/2026-09-30_ux-ia-round2-batch-d.md`、`src/widgets/chat/ContextMeter.tsx`。

## 3. 本机实跑

- 环境：conda `sage-backend`（`D:\programmingSoftware\Anaconda3\envs\sage-backend`；Python 3.11.16、pytest 7.4.4、cryptography 50.0.1），即 AGENTS.md 命令表指定的后端环境。
- 位置：`.worktrees/feat-auto-20261002-f8746de8`（HEAD = `origin/main` @ `38c5f7992`；借用他人 worktree，只读）。运行时加了 `PYTHONDONTWRITEBYTECODE=1`、`-p no:cacheprovider`；但后端测试仍会在仓库根生成被 gitignore 的 `data/`（`sage.db`、`update-metadata/`），已手动清掉，跑完 `git status --ignored` 无任何残留。

```bash
cd backend
pytest tests/unit/chat/test_context_budget_r2d.py   # 6 passed (17.77 s)
pytest tests/unit/chat tests/unit/api               # 623 passed, 1 skipped (43.44 s)
```

- skip 的是 `tests/unit/api/test_wiki_routes.py:82`（环境相关，与批次 D 无关）。
- 未在本机复跑：win7 线（`sage-backend-py38`）、前端 `src/widgets/chat`（vitest）、ruff / tsc / architecture-check。依据：#1864 / #1865 的 CI 均全绿。

## 4. 环境与基线备注

- 本地 `main`（`fbe617925`；根目录 checkout 为 detached HEAD）落后 `origin/main`（`38c5f7992`）30 个提交，所以根目录里看不到批次 D 的代码。按 AGENTS.md 原则 5，不在主 checkout 工作，需要时在 `.worktrees/<名>` 里基于 `origin/main` 开工。
- 不要用 `E:\ProgrammingData\electron\.venvs\sage-ci`（缺 `cryptography`，由 `backend/services/arena_accounts.py` 导入）或 `sage\.venv-ci`（未装 pytest）跑后端测试：`backend/tests/conftest.py` 的 `setup_test_db` 会 `import backend.main`，依赖缺失时全部用例在 setup 阶段 ERROR（不是断言失败）。
- 后端测试（会导入 `backend.main`）会在所在仓库根生成被 gitignore 的 `data/`，`git status` 看不到；在他人 worktree 里借跑之后记得清理。

## 5. 人工实测清单（原文 §4 第 2 条）

前置：聊天路径由环境变量 `API_MODE` 决定（`backend/main.py:987`，代码默认 `legacy`）。legacy 与 `API_MODE=hex` 各测一遍。

1. 在设置里保存一个小窗口模型（建议 ≤ 8k tokens；窗口取自已保存设置，经 `_resolve_effective_window`）。
2. 新建项目，挂 ≥ 4 条较长的项目资料（总量明显超出预算），把与提问相关的那条放在最后。
3. 发一条只与最后那条资料相关的提问。
4. 预期（相关度截断）：相关条目被保留，输出保持原顺序，并带截断说明；`ContextMeter` 来源明细中的项目资料出现截断标记。
5. 预期（回退）：提问与所有条目都不相关，或只有 1 条资料时，行为与批次 D 之前一致（保留开头）。
6. 触发一次技能自动激活：来源明细出现独立的「自动激活的技能」；超预算时它比「技能清单」晚被截、比「项目概览」早被截。
7. 仅 hex：写入一条记忆后再提问，记忆前缀（半角冒号）应计入「记忆召回」。
8. 可选：窗口未知或解析异常时应原样放行（不截断、不报错）。

## 6. 可选后续

- 相关度打分目前是字符二元组重合度；若后续引入本地 embedding，替换 `_truncate_by_relevance` 的打分函数即可（原文 §4）。它不属于批次 D；要做的话，按 AGENTS.md 原则 1 先补 `docs/plans/` 方案文档再写代码。
- 除 §5 的人工实测外，无其他遗留。

## 7. 与 Round 3 的关系

批次 D 与 Round 3（`docs/plans/2026-10-01_ux-ia-round3-panel-slot.md`）没有依赖。Round 3 的 B-2 与 C 按该文档 §7.2 的决策保持阻塞（等 #1867、#1828 合并）；本次核查时 #1828、#1133、#1867 仍为 OPEN。

## 8. 复现命令

```bash
git log origin/main --oneline --grep="UX-IA R2 batch D"
git log origin/release/win7 --oneline --grep="UX-IA R2 batch D"
gh pr view 1864 --json state,mergedAt,statusCheckRollup
gh pr view 1865 --json state,mergedAt,statusCheckRollup
cd backend && pytest tests/unit/chat/test_context_budget_r2d.py
```
