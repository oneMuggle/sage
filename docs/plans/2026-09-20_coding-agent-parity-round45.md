# 编码代理对标差距分析·第四十五轮：CI 事件去重流程化（OPS2）

- **状态**：批次 A 交付中（分支 `feat-ci-rerun-r45`，基线 origin/main 4033a121 = #1391）
- **上游文档**：`docs/plans/parity-rounds-index.md` 优化建议 4；SOP §4.2；
  R28 事件投递中断实证（win7 PR 约 2 小时无 CI）
- **对标对象**：主流仓库的 branch-ci 手动重验通道（worktree 模式仓库的
  常规配套）
- **编号约定**：OPS 系（流程自动化）

## 0. 结论速览

R28 事件中断暴露两个结构性问题：① PR 事件被 GitHub 静默丢弃时**没有任何
自助恢复通道**（workflow_dispatch 跑 ci.yml 会因 job 的 `if` 依赖
pull_request 上下文而整批 skip）；② 需要在事件恢复前对分支做可信验证时
无分支级全量入口。本轮新增 `ci-rerun.yml`：workflow_dispatch 按
`ref + target` 分支手动触发与 ci.yml 同语义的全量验证，All Checks 挂在
分支头 SHA 上，事件恢复前即可恢复 PR 可合并判定。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| OPS2 | PR CI 事件丢失无自助重验通道 | R28：cherry-win7-r28b/r28c/r43 push 数小时无 run | 主流仓库 branch-ci 通道 | **P2** |

## 2. 设计（批次 A：OPS2）

- **ci-rerun.yml**：由 ci.yml 机械派生（脚本提取 6 个 job：backend-py38 /
  backend / dependency-audit / frontend / electron-smoke / all-green），
  语义改动仅三处 `if`：
  - backend-py38 → `inputs.target == 'release/win7'`
  - backend / dependency-audit → `inputs.target == 'main'`
  - frontend / electron-smoke → 无条件（必过项）
  触发器：`workflow_dispatch` + `ref`（分支名）+ `target`（main /
  release/win7）两个输入；checkout 免 ref（dispatch ref 即目标分支）。
- **SOP §4.2 扩展**：写明触发命令
  `gh workflow run ci-rerun.yml -f ref=<分支> -f target=<基线>` 与"事件
  恢复后补真 pull_request CI"的红线不变。
- **测试**：scripts/tests/test_ci_rerun_workflow.py 4 例（触发器输入 /
  backend 按 target 分流 / 必过项无条件 / all-green 汇总键齐全）。

## 3. 批次 A 实施与验证记录

- **生成方式**：脚本机械提取 ci.yml 的 6 个 job（backend-py38 / backend /
  dependency-audit / frontend / electron-smoke / all-green）拼装为
  ci-rerun.yml，保证与强制门步骤逐字一致；语义改动仅三处 `if` 按
  `inputs.target` 分流 + frontend/electron-smoke 去条件。
- **scripts/tests/test_ci_rerun_workflow.py**：4 例结构契约（触发器输入 /
  backend 分流 / 必过项无条件 / all-green 汇总键），每次改 workflow 都会
  被同 PR 的 CI 验证。
- **SOP §4.2**：追加触发命令与语义约定（dispatch 绿解事件死锁，红线仍以
  真 pull_request CI 为准）。
- 验证：YAML 解析 + 4 例结构契约全绿；ruff 全过。前端与业务后端零改动。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：PR #1395（squash `5f329e7a`，CI 14 项全绿）。
- **win7 对齐**：PR #1399（squash `2f83510b`，win7 必过项全绿）。
  同 PR 首次将 parity-loop-sop.md 落入 release/win7（含 §4.2 触发命令）；
  Chat.tsx 导入冲突按 HEAD 侧落位（win7 无 useFileUpload 依赖）。
- **回填分支**：`docs/r45-parity-backfill`（本提交）。
