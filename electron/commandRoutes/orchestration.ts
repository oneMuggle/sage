import type { CommandRoute } from '../commands';

export const orchestrationRoutes: Record<string, CommandRoute> = {
  // orchestration run control
  orchestration_get_run_snapshot: {
    method: 'GET',
    path: (a) => `/api/v1/orch/runs/${encodeURIComponent(String(a.run_id ?? a.runId))}/snapshot`,
  },

  // Phase 3: parent agent steering — POST /orch/runs/{run_id}/tasks/{task_id}/steer
  // Appends a context message (constraint/clarification/additional_context/...)
  // that the executor drains at the next boundary. Returns 409 task_state_changed
  // on CAS revision mismatch.
  orchestration_steer_task: {
    method: 'POST',
    path: (a) =>
      `/api/v1/orch/runs/${encodeURIComponent(String(a.run_id ?? a.runId))}/tasks/${encodeURIComponent(String(a.task_id ?? a.taskId))}/steer`,
  },

  // Phase 3: run cancellation control — POST /orch/runs/{run_id}/cancel
  // Broadcasts run.cancel_requested; executor-driven abort belongs to Phase 4.
  orchestration_cancel_run_control: {
    method: 'POST',
    path: (a) => `/api/v1/orch/runs/${encodeURIComponent(String(a.run_id ?? a.runId))}/cancel`,
  },

  // live-events P1: subagent approval mode — POST /orch/runs/{run_id}/approval-mode
  // body {mode: 'ask' | 'auto'}; 404 when the run is not active in-process.
  orchestration_set_approval_mode: {
    method: 'POST',
    path: (a) =>
      `/api/v1/orch/runs/${encodeURIComponent(String(a.run_id ?? a.runId))}/approval-mode`,
    body: (a) => ({ mode: a.mode }),
  },

  // orchestration (Phase 4: multi-agent coordination)
  orchestration_list_lanes: {
    method: 'GET',
    path: (a) => {
      const params = (a?.params as Record<string, unknown>) ?? {};
      const search = new URLSearchParams();
      if (params.status) search.set('status', String(params.status));
      if (params.team_id) search.set('team_id', String(params.team_id));
      if (params.limit) search.set('limit', String(params.limit));
      const qs = search.toString();
      return `/api/v1/orchestration/lanes${qs ? `?${qs}` : ''}`;
    },
  },
  orchestration_get_lane: {
    method: 'GET',
    path: (a) => `/api/v1/orchestration/lanes/${encodeURIComponent(String(a.lane_id))}`,
  },
  orchestration_list_lane_events: {
    method: 'GET',
    path: (a) => `/api/v1/orchestration/lanes/${encodeURIComponent(String(a.lane_id))}/events`,
  },
  orchestration_cancel_lane: {
    method: 'POST',
    path: (a) => `/api/v1/orchestration/lanes/${encodeURIComponent(String(a.lane_id))}/cancel`,
  },
  // A4: 交付包验收决议 —— POST /lanes/{id}/decision {decision, reason?}。
  // body 显式构造（reason 透传后端审计）。
  orchestration_lane_decision: {
    method: 'POST',
    path: (a) => `/api/v1/orchestration/lanes/${encodeURIComponent(String(a.lane_id))}/decision`,
    body: (a) => ({ decision: a.decision, reason: a.reason ?? '' }),
  },
  // M5: planner-driven lane creation. Body {goal, agent?} — args are
  // auto camelToSnake'd by invokeBackend (both keys stay single-segment).
  orchestration_create_lane: {
    method: 'POST',
    path: () => '/api/v1/orchestration/lanes',
  },
  // P2-5: LaneBoard 快照（freshness_summary + view 投影协商）。
  // GET /api/v1/orchestration/board?view=ops_full|ui_minimal
  orchestration_board: {
    method: 'GET',
    path: (a) => {
      const view = a?.view ? `?view=${encodeURIComponent(String(a.view))}` : '';
      return `/api/v1/orchestration/board${view}`;
    },
  },

  // Wave 2 P1-4 (2026-08-14): run 生命周期 —— plan 更新 / run 取消,
  // 对应 backend/api/orch_routes.py 的 /api/v1/orch/runs 端点。
  // Wave 4 (2026-09-06): 历史编排记录功能移除 —— 删除 list_runs / get_run / resume_run。
  orchestration_cancel_run: {
    method: 'POST',
    path: (a) => `/api/v1/orch/runs/${encodeURIComponent(String(a.run_id))}/cancel`,
  },
  // C1 (2026-09-09): 会话编排 run 列表 —— 历史任务板恢复数据源。
  orchestration_list_session_runs: {
    method: 'GET',
    path: (a) =>
      `/api/v1/orch/runs?session_id=${encodeURIComponent(String(a.session_id))}&limit=${encodeURIComponent(String(a.limit ?? 20))}`,
  },
  // B3 (2026-09-09): 单任务跳过 —— POST /orch/runs/{run_id}/tasks/{task_id}/cancel。
  // queued 任务 acquire 后短路 / running 任务软中断，不影响其余子任务。
  orchestration_cancel_run_task: {
    method: 'POST',
    path: (a) =>
      `/api/v1/orch/runs/${encodeURIComponent(String(a.run_id))}/tasks/${encodeURIComponent(String(a.task_id))}/cancel`,
  },
  orchestration_update_plan: {
    method: 'POST',
    path: (a) => `/api/v1/orch/runs/${encodeURIComponent(String(a.run_id))}/plan`,
    body: (a) => ({ plan: a.plan }),
  },
  // Fix #3 (2026-09-06): 用户确认编排计划 → 唤醒 producer 开始执行。
  orchestration_confirm_run: {
    method: 'POST',
    path: (a) => `/api/v1/orch/runs/${encodeURIComponent(String(a.run_id))}/confirm`,
  },
  // RV2 (round8): 只重跑失败任务 —— 返回 {session_id, goal, plan_override}，
  // 前端经 chatStream planOverride 通道重发。
  orchestration_rerun_failed: {
    method: 'POST',
    path: (a) => `/api/v1/orch/runs/${encodeURIComponent(String(a.run_id))}/rerun-failed`,
  },
  // Round 2 (2026-09-19): 计划模式 × 编排打通 —— 已批准计划文本 → 结构化
  // 任务项（plan_override 形状）。503/502 语义见后端 orch_routes.plan_items。
  orchestration_plan_items: {
    method: 'POST',
    path: () => '/api/v1/orch/plan-items',
    body: (a) => ({ text: a.text }),
  },
};
