# DSH 对标优化·第六轮：审批闸口抽离（GT2）

- **状态**：批次 A 交付中（分支 `feat-dshopt-r6-approval-gate`，基线 origin/main ff654f54）
- **系列定位**：`dsh-opt` 对标系列第 6 轮（总账 [dsh-opt-index.md](dsh-opt-index.md)）。
- **上游文档**：round5（GT1 门控链抽离，main #1468 / win7 #1471）
- **对标对象**：DeepSeek Harness 五段管线 `pre-execute` 的 `ask` 分支——
  审批是管线监听者（"只有 allowed-once 才放行"），事件先流式产出、
  决议回到管线。

## 0. 结论速览

GT1 抽离后 run_loop 仍内联审批闸口（needs_approval → PERMISSION_REQUEST
yield → await 应答 → 决议覆盖，约 22 行，含 yield/await 混合语义）。
本轮抽成 `SageAgent._approval_gate(tc, args, decision, iteration,
result_box)` async generator：先流式产出 PERMISSION_REQUEST（前端先
看到请求，再等应答——顺序契约保持），await 后把最终决议写入
result_box（async generator 无法 return 值）。决议语义逐行保持。

至此五段管线的 **pre-execute 段（deny/ask）全部离开 run_loop 主干**；
GT3（execute around：超时/中断竞争统一包装）与 post-execute 段（钩子
反馈注入）按同路径继续。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| GT2 | 审批闸口内联 run_loop（yield+await 混合，不可单测） | agent.py needs_approval 块 | dsh pre-execute `ask` 监听者 | **P2** |

## 2. 设计（批次 A：GT2）

- `async def _approval_gate(tc, args, decision, iteration, result_box)
  -> AsyncIterator[AgentEvent]`：
  1. `_build_approval_request` 构造请求；
  2. yield PERMISSION_REQUEST（携带 to_dict 载荷、iteration、agent_id）；
  3. `await _await_approval_answer`（gate 未装配 default-deny，不变）；
  4. 决议写 `result_box["decision"]`：approved → allowed=True（reason 附
     "用户已批准"）；否则 allowed=False（reason 附 "未获批准:
     answered_by"）。
- run_loop 侧：`async for` 透传闸口事件 + `decision = gate_result["decision"]`，
  后续拒绝分支不变。

## 3. 批次 A 实施与验证记录

- **抽离**：`_approval_gate` async generator（yield PERMISSION_REQUEST →
  await 应答 → result_box["decision"] 决议）；run_loop 侧 `async for`
  透传 + 读取决议，后续拒绝分支零改动。
- **测试**：+4 例（事件先于 await 的顺序契约 / 批准决议 / 拒绝携带
  answered_by / iteration+agent_id 载荷）。夹具踩坑一次：
  PermissionDecision 不变量 needs_approval=True 时 allowed 必须为
  False（enforcer 的 ask 状态），已按真实语义修正。
- **验证**：新测 4 例 + GT1/loop_guards/execution_groups 回归 18 例
  全绿；ruff 全过；py38 护栏（compat_rewrite --check 0 变更 + AST 3.8）
  通过；baseline 同步（agent.py 2391）。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：（PR 占位）
- **win7 对齐**：（cherry-pick 占位）
