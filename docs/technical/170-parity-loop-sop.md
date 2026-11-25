# 170 · 对标迭代 SOP

## 1. 背景与定位

Sage 同时维护 `main` 与 `release/win7` 两条长期分支，新能力默认要在两条分支上落地。对标迭代（parity loop）把「差距分析 → 单批次交付 → 双分支对齐」固化成可重复执行的步骤，目标是让任何会话或任何人都能按图索骥地完成一轮能力对标落地。

适用范围：

- 针对 Claude Code / Cursor / Devin 等编码代理做能力对标后，需要跨 main 与 release/win7 交付的功能。
- 需要同时产出代码、测试与文档的批次化改进。

不适用：

- 纯依赖升级、纯线上事故 hotfix 等不涉及对标差距的改动——走常规 `feat/*` / `fix/*` 流程即可。
- 只影响单分支的 Win7 专有兼容修复（这类修复不回灌 main）。

早期轮次的交付总账（原 `parity-rounds-index.md`）已随计划目录清理归档，本文不再依赖该索引；每轮的可追溯性由 PR 号、squash SHA 与 `§回填` 保证。

## 2. 相关文件与入口

| 文件 / 目录 | 作用 |
| --- | --- |
| `scripts/worktree.sh` | 开 worktree 并分配独立端口对（`new/list/ports/remove/clean`），端口写入 `.env.local` |
| `docs/technical/47-git-worktree-workflow.md` | worktree 完整用法、`.claude/worktrees/` 隔离边界与故障排查 |
| `scripts/check_py38_compat.py` | py38 AST 护栏（默认检查 `backend/`、`packages/sage-core/`） |
| `scripts/py38_compat_rewrite.py` | 护栏命中的语法自动改写辅助 |
| `backend/ruff.toml` | backend lint 配置；py38 兼容下禁用 UP006/UP007/UP035，DTZ 仅保留 DTZ001 等检查 |
| `lefthook.yml` / `scripts/lint.sh` / `scripts/pytest.sh` | 本地 hook 与可移植的 lint/test 包装 |
| `.github/workflows/ci.yml` | 主 CI（main、py38、coverage ≥ 80 等） |
| `.github/workflows/ci-rerun.yml` | PR 事件丢失时的 `workflow_dispatch` 手动全量重验 |
| `backend/api/orch_routes.py` | 编排 run/task 查询端点（会话级历史） |
| `backend/data/database.py`、`backend/data/migrations/v21_orch_tasks_composite_pk.py` | `orch_tasks` 表结构与 `(run_id, task_id)` 复合主键迁移 |
| `backend/data/usage_cost_repo.py` | 按 `run_id` 聚合 `usage_events` 金额 |
| `src/widgets/chat/progress/SessionRunHistory.tsx` | 会话级历史编排浏览器 |
| `backend/requirements.txt`、`backend/requirements-py38.txt` | 依赖钉版（main 用 pydantic 2.5.0 等） |
| `release/win7` 分支：`backend/requirements-py38.txt`、`backend/compat/win7/pydantic_compat.py` | win7 分支钉 pydantic 1.10.13 并提供 v1/v2 兼容垫片（main 无 `backend/compat/`） |

## 3. 循环步骤（每轮）

1. **差距分析**：先 `git log origin/main --oneline -20` 扫最新合并，避免与并行会话撞车道；挑一个可验证、可单批次交付的差距，参考对标对象给出优先级。
2. **worktree**：优先用 `scripts/worktree.sh new feat-<域>-r<N> --base main`（自动分配独立端口对到 `.env.local`，用 `set -a && source .env.local && set +a` 生效）。等价的手工方式：
   ```bash
   git fetch origin main
   git worktree add .worktrees/feat-<域>-r<N>-batch-a \
     -b feat-<域>-r<N>-batch-a origin/main
   ```
   cwd 被删导致 spawn 报错时见 §6.1。
3. **方案文档**：在 `docs/plans/` 写本轮方案（结论速览 / 差距矩阵 / 设计 / 实施记录 / 交付号占位）。按文档治理，计划文档只保留在途轮次；交付完成后其结论并入对应技术章节，计划文件删除，不长期堆积。
4. **实施**：小步提交；本地验证按 §5 矩阵执行。
5. **PR**：标题与提交标题一致；正文三段式——差距证据 / 变更 / 验证。
6. **CI**：`gh run watch <run-id> --exit-status`；全绿后 `gh pr merge --squash --delete-branch`，记录 squash SHA。
7. **win7 对齐**：优先 `git cherry-pick <main-squash-sha>`（干净率最高）；本地跑受影响测试 + py38 护栏后推分支，开 PR（base 为 `release/win7`）→ CI 绿 → merge。冲突时 `git merge origin/release/win7` 解冲突后再推。cherry-pick 后必须按 §6.4 diff 回 win7 基线复核。
8. **§回填**：在 `docs/rXX-parity-backfill` 分支回填本轮 main / win7 的 PR 号与 squash SHA，走 docs PR 合入 main；随后按文档治理清理计划文件。
9. **清理**：删除本轮全部 worktree 与本地/远程分支。删除前确认前台 shell 的 cwd 不在该 worktree 内（见 §6.1）。

## 4. win7（py38）兼容检查清单

- **语法层**：`scripts/check_py38_compat.py` 通过（AST 解析 + 四类 3.9+/3.10+ 语法检测）。
- **注解扫描**：无 `X | Y`（PEP 604）、无 PEP 585 内建泛型直接标注；统一 `Optional[X]` / `List[X]` / `Dict[K, V]`。
- **f-string**：不在 f-string 内嵌套同引号（py38 不支持）；复杂拼接用 `%` 或预变量。
- **pydantic 运行时 API**（语法护栏查不出）：
  - 分支钉版：`release/win7` 用 `pydantic==1.10.13` + `fastapi==0.109.1`（v1 API）；`main` 用 `pydantic==2.5.0` + `fastapi==0.109.1`（v2 API）。main 的 `backend/requirements-py38.txt` 同样钉 2.5.0（2.6+ 才弃 3.8）。因此「2.x 需要 3.9+」的说法不成立——两分支真正的分歧是 v1 与 v2 的 API 形态，不是解释器下限。
  - v2-only 导入（如 `from pydantic import ConfigDict`）在 cherry-pick 到 `release/win7` 后，改从该分支自带的垫片 `backend.compat.win7.pydantic_compat` 导入（模块导入即自动 `install()`，与 `workspace_routes` 同套路）。该目录只在 `release/win7` 存在，main 不需要也不要创建。
  - `model_dump` 等新 API 由垫片覆盖，但**没有 `model_rebuild` 垫片**：跨模型前向引用按依赖顺序定义类消除即可，不要依赖 `model_rebuild`。
  - `Field(pattern=...)` 在 pydantic v1 被静默忽略（既不报错也不生效）；相关路由内要有等价校验兜底。
- **本地测试**：受影响测试在本地解释器全绿——但不能替代真 py38 CI。
- **cherry-pick 后 diff 回 win7 基线**：main 侧 hunk 可能静默冲掉 win7-only 代码（如 `get_connection` 的代理身份绑定、审计策略、ci-win7 语义）。

## 5. 本地验证矩阵（按改动类型）

| 改动 | 必跑 |
| --- | --- |
| backend py | 受影响 pytest 文件 + `ruff check <files>` |
| 前端 ts/tsx | 受影响 vitest + `npm run typecheck` + `eslint <files>` |
| settings/UI | 对应 `__tests__` + 有新键时同步默认值常量（如 `DEFAULT_SETTINGS`）与契约测试 |
| DB schema | 迁移幂等（新库 + 旧库两条路径各跑一次 `init_db`） |
| 文档 | grep 确认锚点存在（python heredoc 易静默失败） |

## 6. 已知坑与处置

### 6.1 spawn ENOENT ≠ 解释器损坏（先查 cwd）

常驻 shell 的 cwd 指向被删除的 worktree 时，一切 spawn 报 `ENOENT`（Windows 上常表现为 `bash.exe ENOENT`），极易误诊为工具链损坏。处置：`cd` 回存在的目录（必要时先新建目录占位）即可恢复，无需重装 Git。Windows 上若确系 `bash.exe` 真损坏，才用 `copy /y Git\usr\bin\bash.exe Git\bin\bash.exe`（历史有先例但罕见）。

### 6.2 GitHub 事件静默丢弃 → ci-rerun 手动重验

高频 push 时 PR 事件可能数小时不触发 CI。缓解：多轮内容合并为单个 PR 以减少事件量；用 `workflow_dispatch` 做分支级验证；事件恢复后必须补真 pull_request CI。

`.github/workflows/ci-rerun.yml` 提供与 `ci.yml` 同语义的手动全量重验（check 挂到分支头 SHA，恢复 PR 可合并判定）：

```bash
# main 目标分支（backend 跑 py3.11 套件）
gh workflow run ci-rerun.yml --ref <分支名> -f ref=<分支名> -f target=main

# release/win7 目标分支（backend 跑 py38 套件）
gh workflow run ci-rerun.yml --ref <分支名> -f ref=<分支名> -f target=release/win7
```

`--ref` 与 `-f ref=` **缺一不可**：

- `-f ref=` 是本 workflow 的输入，决定各 job checkout 哪个分支；
- `--ref` 决定 run 挂在哪个 ref、check-run 记到哪个 commit。

漏掉 `--ref` 时 gh 回退到当前检出分支（在主检出的 detached HEAD 上会落到默认分支 main），run 照跑、All Checks 照绿，但 check-run 全记在错误 SHA 上，对目标 PR 完全无效。dispatch 后请立刻核对 `GET /actions/runs/<id>` 的 `head_sha` 是否等于 PR head SHA。

语义约定：`target=release/win7` 时 backend-py38 全量运行；`target=main` 时 backend 跑 py3.11 套件；frontend、desktop-build 与 electron-smoke 永远运行；两个 backend 都 skip 时 all-green 按既定例外通过。**红线**：dispatch 绿只解「事件丢弃」的死锁，事件恢复后仍以真 pull_request CI 为准。

### 6.3 分支命名碰撞

多会话并行时 `docs/rXX-backfill` 这类通用名会被撞。回填/工具分支用带域前缀的独占名：`docs/rXX-parity-backfill`。删除「别人名下」的本地分支前先 `git ls-remote origin <branch>` 确认归属。

### 6.4 diff-patch ≠ cherry-pick

从 main 搬 hunk 到 win7 时，win7-only 代码会被「看起来正确」的 main 上下文覆盖。cherry-pick 失败时宁可手工解冲突，也不要整文件替换；能干净 cherry-pick 就不用 diff-patch，diff-patch 后必须 diff 回 `release/win7` 基线复核。

### 6.5 main CI 绿 ≠ win7 兼容

两类只有 win7 侧才会暴露的坑：

1. **pydantic v2-only API**：main 用 2.5（v2），win7 锁 1.10.13（v1）。函数体内 `BranchesResponse.model_rebuild()` 这类调用在 main 全绿，cherry 到 win7 后运行时 `AttributeError`，只有 `Backend (Python 3.8, Win7 LTS)` job 能抓到。处置见 §4。
2. **import 结构漂移**：win7 文件可能有 main 没有的模块级导入（如 `main.py` 的 `get_database`）。main 代码在函数内 `from X import name` 无害，win7 上却使 `name` 在整个函数内变局部名 → 先用后导，ruff F823 + 运行时 `UnboundLocalError`（win7 直接炸启动）。

本地防线：`sage-backend-py38` conda env（Python 3.8.20 + pydantic 1.10.13，`cryptography` 已可用）跑受影响测试 + `import backend.main` 冒烟，别等 CI。本地默认开发环境 `sage-backend` 为 Python 3.10.20，与 win7 的主要差异仍是 pydantic v1/v2 与语法层，真 py38 CI 不可省。

### 6.6 本地 hook 环境缺失（node / conda）

`lefthook.yml` 对依赖 node 的命令都带环境前置检查：缺 node 或 `node_modules` 时打一行 skip 并以 `exit 0` 放行（不再以 `exit 127` 硬拦 commit/push）；backend 命令经 `scripts/lint.sh` / `scripts/pytest.sh` 包装，`scripts/pytest.sh` 在 pytest 完全不可用时同样 warning + 放行。即本地 hook 不会因缺环境阻塞推送。仍需注意：

- 被跳过不等于验证过——CI 全量套件才是 merge 的唯一硬门。
- 当前 `lefthook.yml` 没有配置 `prepare-commit-msg` 命令，cherry-pick 不会被本地 hook 拦截；若遇到其他 hook 干扰，可用 `git -c core.hooksPath=/dev/null cherry-pick …` 或 `git push --no-verify` 临时绕过，事后仍以 CI 为准。

### 6.7 午夜/时钟 flake（DTZ）

`now ± hours` 构造测试数据会在 UTC 23:00–01:00 窗口跨界。根治：monkeypatch 冻结被测模块的 `datetime`（返回固定时刻），due/时间戳全部由冻结值推导；锚定「今日 00:00」只对单日边界有效，凌晨 01:00 后仍会翻车。冻结的 `datetime(...)` 需 `DTZ001` noqa（刻意 naive，与服务 naive now 的口径一致）。`backend/ruff.toml` 选中 DTZ 但忽略 DTZ005/DTZ006，DTZ001 仍生效。

### 6.8 base 前进不会自动重跑 PR CI

pull_request 工作流只在 head synchronize/opened 触发；main/release 推进后 PR 检查不会自动重跑。处置：`git rebase origin/<base>` + `git push --force-with-lease` 触发全新 run。另注意：`gh run list --limit 1` 在 push 后约 40s 内可能拿到旧 run——先 `sleep 45` 再查。

### 6.9 网络抖动（SSL reset / Head sha can't be blank）

push / pr create 高频出现 SSL reset；「Head sha can't be blank」即分支没推上去。处置：带退出码判定的重试循环（管道 exit code 会骗人，用 `if git push …; then` 而非 `… | tail -1`）；GitHub CLI 偶发路径丢失时用绝对路径（Git Bash 示例：`/d/software/Scoop/shims/gh.exe`）；远端分支删除失败可用 `gh api -X DELETE repos/…/git/refs/heads/<branch>` 兜底。

## 7. 交付质量红线

- **无绿不 merge**：workflow_dispatch 的分支验证不能替代真 PR CI，两者全绿才算闭环。
- **测试随轮交付**：代码与测试同 PR，不为赶进度先合代码后补测试（会变成下轮技术债）。
- **方案文档随轮交付**，PR 号与 squash SHA 当轮或次日回填。轮次交付总账保留在 `docs/plans/parity-rounds-index.md`（`docs/plans/` 只保留这类仍在维护的索引与未完成计划）；已交付功能的方案文档随交付并入技术章节后删除。

## 8. 已知遗留：orch_tasks 历史视图（待产品决策）

这是对标迭代中唯一尚未收口的功能项，数据层与会话级展示已就绪，但更广的「历史视图」缺产品口径。

**现状（以代码为准）**

- **数据层已具备**：`orch_tasks` 持久化 `used_tokens` / `duration_ms`（RT24）；`v21_orch_tasks_composite_pk.py` 把主键改为 `(run_id, task_id)`，多 run 的同名 task 行不再互相覆盖；`usage_events` 账本按 `run_id` 聚合金额（`usage_cost_repo.run_costs_usd`，M4.3b）。
- **会话级历史已可用**：`GET /api/v1/orch/runs?session_id=&limit=`（`limit` 默认 20，范围 1–100）返回当前会话的 run 列表（`SessionRunsResponse`），包含每任务 `used_tokens` / `duration_ms` / `cost_usd` 与 run 级 `total_used_tokens` / `total_duration_ms` / `cost_usd`；前端 `SessionRunHistory`（RD23 / RD24 / RD26）提供「历史编排」折叠面板，点击某 run 通过 `restoreRunToBoard` 切回该 run 的任务板。
- **恢复链路已打通**：R43 的 `restoreRunToBoard` 能把历史 run 的字段还原到任务板。

**待决策（唯一遗留）**

- 面向「跨 run / 任务级」的历史视图（例如全局按任务维度浏览历史、跨 run 的消耗与重派链聚合、筛选与排序）仍缺产品口径：展示哪些维度、金额与 token 如何归因、是否允许跨会话查询、默认排序与分页策略等。
- Wave 4 曾移除无过滤的 `GET /runs`，当前 API 仅暴露会话级归属过滤。因此该视图不能简单「恢复旧端点」，必须先定展示口径再设计接口。

**口径确定前不做**

- 不新增无归属过滤的全量历史端点；
- 不在前端堆临时聚合逻辑；
- 不把会话级面板当作全局任务历史使用。

---

本 SOP 由对标循环维护；发现新坑直接追加 §6。
