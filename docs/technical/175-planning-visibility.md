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
