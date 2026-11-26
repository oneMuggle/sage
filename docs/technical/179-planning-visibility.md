# 编排规划可见性（plan_progress）

## 事件协议

`state = "plan_progress"`，载荷固定为 `plan_progress` 对象：

- `stage`：mode_classify | complexity_classify | clarify | scout | scout_deep | decompose
- `status`：started | progress | done | skipped | failed
- `kind`：message | thinking | tool_call | tool_result | reasoning | heartbeat | skip_reason | error
- `text`：人类可读单行（≤500 字符）
- `detail`：结构化附加信息（默认 `{}`）
- `elapsed_ms`：阶段耗时（可缺省）

## 后端

- `backend/orchestration/plan_progress.py` 提供 `emit_plan_progress` / `run_planning_stage` / `emit_planning_skipped`。
- `run_planning_stage` 每 5 秒发心跳；异常原样上抛；取消时补发 failed 后继续上抛。
- 接入点：`legacy_routes.py`（模式判定、拆解）、`plan_preflight.py`（复杂度、澄清、侦察、深度调研）。

## 前端

- `planProgress.ts` 纯 reducer 合并事件（同阶段 20 行上限）。
- `chatStreamStore` 新增 `planProgress` 槽位。
- `PlanningTimeline` 内联在 assistant 气泡。

## 已知修复

- `orch_preflight` 历史字段名为 `phase`，前端现同时读取 `phase` 与 `preflight_phase`，粗粒度指示条恢复渲染。

## P2：调研实时化

- 澄清（clarify）、侦察（scout）、深度调研（scout_deep）阶段接入 `plan_progress`，逐步实时展示提问、工具调用与调研结果。
- 前端 `send-message` 事件循环增量合并 `plan_progress`，气泡内时间线随阶段推进实时刷新，无需等到整段结束。

## P3：流式拆解与前哨优化

- 拆解（decompose）阶段以流式方式回传思考与步骤；`make_stream_progress_emitter` 按「≥200 字符或 ≥0.6 秒」缓冲后批量上屏，避免逐 token 抖动。
- 规划前哨小任务（模式/复杂度分类、澄清、侦察）改用 utility LLM 客户端：默认关闭思考（`reasoning_effort="low"`、`thinking_budget=0`），降低推理模型在小任务上的长思考开销。
- `build_utility_llm_client(task_type=...)` 仅在显式传入 `task_type` 时应用按用途路由；侦察需要工具调用，故不传 `task_type`（不加路由 overlay）。
- `complete_utility` 在客户端构建或调用失败时回退到普通客户端，绝不阻塞编排。
