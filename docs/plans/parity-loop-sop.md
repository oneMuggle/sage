# 对标改进循环 SOP（标准作业程序）

> 目标：让"对标 → 交付"循环可被任何会话/任何人按图索骥地重复执行。
> 配套：交付索引见 [parity-rounds-index.md](parity-rounds-index.md)。
> 本 SOP 沉淀自 R7-R40 共 30+ 轮双分支交付的实战复盘。

## 1. 循环步骤（每轮）

1. **差距分析**：在本会话负责的领域内（避免与他人并行会话撞车道——
   先 `git log origin/main --oneline -20` 扫最新合并），找一个可验证、
   可单批次交付的差距；对标对象（Claude Code/Cursor/Devin）给优先级。
2. **worktree**：`git fetch origin main && git worktree add
   .worktrees/feat-<域>-r<N>-batch-a -b feat-<域>-r<N>-batch-a origin/main`。
   ⚠ 若上一轮删除 worktree 后 spawn ENOENT，见 §4.1。
3. **方案文档**：`docs/plans/<date>_coding-agent-parity-round<N>.md`
   （结论速览 / 差距矩阵 / 设计 / §3 实施记录 / §5 交付号占位）。
4. **实施**：小步提交；本地验证矩阵见 §3。
5. **PR**：标题 = 提交标题；正文三段式（差距证据 / 变更 / 验证）。
6. **CI**：`gh run watch <run> --exit-status`；绿后
   `gh pr merge --squash --delete-branch`，记录 squash SHA。
7. **win7 对齐**：优先 `git cherry-pick <main-squash-sha>`（干净率最高）；
   本地跑受影响测试 + py38 护栏（AST + `|` 注解扫描）后推分支开 PR
   （base release/win7）→ CI 绿 → merge。冲突时 `git merge
   origin/release/win7` 解冲突后再推。
8. **§回填**：`docs/rXX-parity-backfill` 分支回填 §5（main/win7 PR 号与
   SHA），走 docs PR 合入 main。
9. **清理**：删除全部本轮 worktree 与本地/远程分支；
   ⚠ 删除前确认前台 shell 的 cwd 不在该 worktree 内（见 §4.1）。

## 2. win7（py38）兼容检查清单

- AST 解析通过（语法层）；
- 注解扫描：无 `X | Y`（PEP 604）、无 PEP 585 内建泛型直接标注；
  统一 `Optional[X]` / `List[X]`；
- f-string 内不再嵌套同引号（py38 不支持），复杂拼接用 `%` 或预变量；
- **pydantic 运行时 API**：win7 锁 1.10.13（2.x 需 py3.9+），语法护栏查不出——
  `from pydantic import ConfigDict` 改从 `backend.compat.win7.pydantic_compat`
  导入（模块顶层自动 install，与 workspace_routes 同套路）；`model_dump` 等由
  垫片覆盖，但 **`model_rebuild` 垫片没有**，跨模型引用按依赖顺序定义类消除
  前向引用即可删掉它；`Field(pattern=...)` 在 v1 被静默忽略，路由内要有等价
  校验兜底（详见 §4.5）；
- 相关测试在本地解释器全绿（本地 3.12 通过 ⇒ 语义大概率 OK，
  但语法护栏与真 py38 CI 不可省）；
- **cherry-pick 后必须 diff 回 release/win7 基线**：main 侧 hunk 可能
  静默冲掉 win7-only 代码（R23 实证：get_connection 代理身份绑定、
  审计策略、ci-win7 语义）。

## 3. 本地验证矩阵（按改动类型）

| 改动 | 必跑 |
| --- | --- |
| backend py | 受影响 pytest 文件 + `ruff check <files>` |
| 前端 ts/tsx | 受影响 vitest + `npm run typecheck` + `eslint <files>` |
| settings/UI | 对应 __tests__ + 有新键时 `DEFAULT_*` 同步检查 |
| DB schema | 迁移幂等（新库+旧库双路径各跑一次 init_db） |
| 文档 | grep 确认锚点存在（python heredoc 易静默失败） |

## 4. 已知坑与处置

### 4.1 spawn ENOENT ≠ bash.exe 损坏（先查 cwd！）
worktree 被删除后，常驻 shell 的 cwd 失效 → 一切 spawn 报
`bash.exe ENOENT`，极易误诊。处置：用 Write 工具在「被删目录」写一个
占位文件 → spawn 恢复 → `cd` 回主仓库 → 清理占位目录。
（若确系 bash.exe 损坏：`copy /y Git\usr\bin\bash.exe Git\bin\bash.exe`，
历史上有先例但罕见。）

### 4.2 GitHub 事件静默丢弃
高频 push 期 PR 事件可能数小时不触发 CI（R28 实证）。缓解：多轮内容
合并为单个 PR 减事件量；用 workflow_dispatch 做分支级验证（注意 job
的 `if` 对非 PR 事件的语义）；push 恢复后必须补真 pull_request CI。

### 4.3 分支命名碰撞
多会话并行时 `docs/rXX-backfill` 这类通用名会被撞（R36 实证）。
回填/工具分支用带域前缀的独占名：`docs/rXX-parity-backfill`。
删除"别人名下"的本地分支前先 `git ls-remote origin <branch>` 确认归属。

### 4.4 diff-patch ≠ cherry-pick
从 main 搬 hunk 到 win7 分支时，win7-only 代码会被"看起来正确"的
main 上下文覆盖（R23 三坑）。cherry-pick 失败时宁可手工解冲突，
也不要整文件替换。

### 4.5 main CI 绿 ≠ win7 兼容（#1308→#1321 实证）
两类只有 win7 侧才暴露的坑：
1. **pydantic v2-only API**：main 用 2.5、win7 锁 1.10.13。函数体内
   `BranchesResponse.model_rebuild()` 这类调用在 main 全绿，cherry 到
   win7 后 import 即 AttributeError，只有 `Backend (Python 3.8, Win7
   LTS)` job 能抓到。处置见 §2 垫片条目。
2. **import 结构漂移**：win7 文件可能有 main 没有的模块级导入
   （如 main.py 的 `get_database`）。main 代码在函数内 `from X import
   name` 无害，win7 上却使 `name` 在整个函数内变局部名 → 先用后导
   ruff F823 + 运行时 UnboundLocalError（win7 直接炸启动）。
本地防线：`sage-backend-py38` conda env（3.8.20 + pydantic 1.10.13，
与 requirements-py38.txt 同版本）跑受影响测试 + `import backend.main`
冒烟，别等 CI（该 env 缺 `cryptography`，test_arena_routes 本地收集
不了属既有环境缺口）。

## 5. 交付质量红线

- 无绿不 merge（workflow_dispatch 的分支验证不能替代真 PR CI；
  两者全绿才算数）；
- 测试随轮交付（R23 教训：代码合了测试没合，下轮补测算技术债）；
- 方案文档随轮交付且 §5 当轮或次日回填，总账
  [parity-rounds-index.md](parity-rounds-index.md) 随轮追加行。

—— 本 SOP 由对标循环维护；发现新坑直接追加 §4。
