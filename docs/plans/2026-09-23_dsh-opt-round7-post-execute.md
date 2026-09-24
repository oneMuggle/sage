# DSH 对标优化·第七轮：post-execute 段抽离（GT3）

- **状态**：批次 A 交付中（分支 `feat-dshopt-r7-post-execute`，基线 origin/main a7591778）
- **系列定位**：`dsh-opt` 对标系列第 7 轮（总账 [dsh-opt-index.md](dsh-opt-index.md)）。
- **上游文档**：round5（GT1）、round6（GT2）
- **对标对象**：DeepSeek Harness 五段管线的 `post-execute`（observe-only）
  与 `result` 段——结果落历史、反馈注入、错误钩子都是管线监听者。

## 0. 结论速览

GT1/GT2 完成 pre-execute 段（deny/ask）抽离后，串行管线仍内联
post-execute 段（tool 结果消息落历史 + post_tool_use 反馈注入 +
error_occurred 钩子，约 45 行）。本轮抽成
`_post_tool_observe(tc, args, m6_hooks, messages, result_content,
is_error, cap_fn)`。至此五段管线的 pre-execute（GT1/GT2）、
execute-around（既有 `_await_tool_execution`）、post-execute（GT3）
全部离开 run_loop 主干——**B1 方向达成第一个里程碑**；
OBSERVING 事件（loop 专属 iteration 语义）仍在 run_loop，`accept/block`
语义（post-execute 可修改结果）按 dsh 口径留后续轮次。

`cap_fn` 参数：`cap_result_for_context` 是捕获 run 级截断预算状态的
闭包（`nonlocal remaining_budget`），由调用方注入以保持预算语义。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| GT3 | post-execute 段内联 run_loop（落历史/反馈/错误钩子） | agent.py 串行路径 45 行内联 | dsh post-execute + result 监听者 | **P2** |

## 2. 设计（批次 A：GT3）

- `_post_tool_observe(tc, args, m6_hooks, messages, result_content,
  is_error, cap_fn)`：
  1. capped tool 结果消息落对话历史（cap_fn 注入）；
  2. `post_tool_use` 钩子（observe-only）：`additional_context` 按期
     severity 以 system 角色注入；
  3. `error_occurred` 钩子（observe-only，内部按 is_error 过滤）。
- 并行池分支有自己的变体（tc_p 语义 + parallel_outcome），本轮不动。
- run_loop 串行路径调用点单行化。

## 3. 批次 A 实施与验证记录

- **抽离**：`_post_tool_observe`（cap_fn 注入 run 级截断闭包）；串行
  路径调用点单行化，OBSERVING 事件保留在 run_loop（iteration 语义）。
- **测试**：+4 例（capped 落历史 / severity 反馈注入 / error 钩子
  is_error 透传 / 无反馈零额外消息）。两坑记录：`cap_result_for_context`
  是 run 级闭包不可模块化（改参数注入）；`_maybe_fire_error_hook` 内部
  自行按 is_error 过滤（方法无条件调用，测试断言透传而非次数条件）。
- **验证**：新测 4 例 + 管线回归 28 例全绿（tool_gate / approval_gate /
  execution_groups / loop_guards）；ruff 全过；py38 护栏（compat_rewrite
  --check 0 变更 + AST 3.8）通过；baseline 同步（agent.py 2428）。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：（PR 占位）
- **win7 对齐**：（cherry-pick 占位）
