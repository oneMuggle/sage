# 编排 Round 4——验收结果进复核 + 完成定义进任务（验收闭环硬化）

> 日期: 2026-09-19
> 前序: #1218（编排计划前置 Round 1-3，已合并）
> 目标分支: feat/orch-acceptance-review → main

## 背景

编排验证环现状（A4/P0-2）：
- `executor` 在 lane 成功后跑自动验收（`acceptance.py`：git diff --stat +
  pytest/tsc 白名单探测），结果只落 `lane.acceptance.completed` 事件供
  交付抽屉展示——**设计上"advisory，绝不翻转 lane 结论"**；
- `review.run_review` 的 reviewer 只看聚合文本，**不知道**验收检查结果；
- Planner / plan-items 产出的任务描述没有"完成定义"，子代理与 reviewer
  都缺少可检验的验收口径。

结果：验收失败既不影响 reviewer verdict，也不进入 conductor 的修复上下文
——验收环与验证环两条线平行，闭环断在中间。

## 方案（三处接线，全部后端）

### 1. executor：验收摘要随 lane 结果回传

`_run_acceptance` 返回 `AcceptanceReport`；`execute_lane` 成功路径把摘要
放进返回 dict：

```python
{"status": "succeeded", "lane_id": ..., "result": ..., "acceptance": {
    "all_passed": bool, "checks": [{name, passed, skipped, summary}, ...]}}
```

不改变既有事件/结论语义（advisory 铁律不变——检查失败不翻转 lane 状态）。

### 2. dispatcher：聚合时收集 → 注入 reviewer 输入

- `ChatTaskState` + `acceptance` 字段；lane 执行后（`run_lane_with_retry`
  返回处）回填 `state.acceptance`。
- 新模块级纯函数 `build_acceptance_block(states)`：有验收记录的子任务
  生成 markdown 区块（总数/未通过数 + 未通过明细行，含 task_id 与
  check 摘要截断）；无任何验收记录 → 空串（行为与现状一致）。
- `_aggregate` 复核触发处：`self._run_review(aggregated, acceptance_block=block)`。
- `_run_review` 加可选参数透传 `review.run_review`（默认空串，既有调用
  与测试兼容）。
- `review.run_review` + 新纯函数 `build_review_goal(aggregated,
  acceptance_block, max_chars)`：block 非空时置于 reviewer 目标最前，
  并附指令——"存在未通过项且聚合结果未解决 → 给该子任务 NEGATIVE_EVIDENCE
  assertion（confidence ≥ 0.7）"，从而联动既有 verdict 规则
  （NEGATIVE_EVIDENCE ≥0.7 → fail）与既有修复循环（fail → conductor
  修复后再汇总）及重跑失败任务按钮（RV2/round27）。

### 3. 拆解提示词：任务描述携带完成定义

- `planner.py` 拆解指令第 4 条：description 需含
  `做什么 / 涉及对象 / 预期产出 / 完成定义（验收标准）`；
- `orch_routes.plan_items` 结构化要求 1 同步补"可检验的完成定义"。

goal 自包含语义不变——完成定义随 goal 流入子代理 prompt、task_plan、
orch_tasks 落库与 PlanCard（可在确认门编辑）。

## 非目标

- TaskPacket.acceptance_tests 结构化激活（本期验收标准随 goal 文本流转，
  无 schema 变更；结构化字段留待验收门禁真正 gate lane 结论时再做）。
- 验收失败自动触发单任务重试（先人工/人工确认按钮，自动化留观）。

## 验收

- 新增 `tests/unit/test_acceptance_review.py`：
  - `build_review_goal` 含/不含 block 的组合与截断；
  - `build_acceptance_block`：无记录→空串 / 全通过→仅头部 /
    存在未通过→含 task_id 明细与截断；
  - dispatcher `_aggregate` 触发复核时把 block 透传 `run_review`
    （patch 捕获 kwargs）；
  - executor 成功返回携带 acceptance 摘要（patch run_acceptance_checks）；
  - planner / plan-items 提示词含"完成定义"。
- 存量：`test_chat_dispatcher_review_event.py`（`_run_review` 旧签名调用
  兼容）、`test_acceptance.py`、`test_planner_llm.py` 全绿。

## Win7 对齐

纯后端 Python（py3.8 兼容写法），合并后可直接 cherry-pick。
