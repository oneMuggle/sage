/**
 * IPC client for run-control endpoints (snapshot / steer / cancel).
 *
 * Complements orchRunClient.ts (run CRUD) with the realtime monitoring
 * endpoints added in Phase 1 of the subagent-realtime-monitoring plan.
 *
 * Transport: Electron IPC invoke → backend HTTP.
 * For the NDJSON event stream, use orchEventStream.ts (fetch-based) instead.
 */

import { invoke } from './desktopInvoke';
import type { RunSnapshot } from './orchEvents';

export interface SteerTaskParams {
  run_id: string;
  task_id: string;
  message_type: 'constraint' | 'clarification' | 'additional_context' | 'correction' | 'priority_update' | 'reference';
  content: string;
  apply_mode?: 'next_boundary' | 'new_followup';
  expected_task_revision?: number;
}

export interface SteerTaskResponse {
  ok: boolean;
  context_id: string;
  status: string;
}

export interface CancelRunParams {
  run_id: string;
  reason?: string;
}

export interface CancelRunResponse {
  ok: boolean;
  run_id: string;
  status: string;
}

export const orchRunControlClient = {
  /** GET /orch/runs/{runId}/snapshot */
  async getSnapshot(runId: string): Promise<RunSnapshot> {
    return invoke<RunSnapshot>('orchestration_get_run_snapshot', { run_id: runId });
  },

  /**
   * POST /orch/runs/{runId}/tasks/{taskId}/steer
   *
   * Phase 3: Parent agent steering. Body shape:
   *   { source, message_type, content_redacted, apply_mode, expected_task_revision, created_by }
   *
   * Returns 409 `{ error: "task_state_changed" }` on CAS revision mismatch.
   * Returns 409 `{ error: "task_terminal" }` if task already succeeded/failed/cancelled.
   */
  async steerTask(params: SteerTaskParams): Promise<SteerTaskResponse> {
    return invoke<SteerTaskResponse>('orchestration_steer_task', { ...params });
  },

  /**
   * POST /orch/runs/{runId}/cancel
   *
   * Phase 3: Run cancellation control. Broadcasts `run.cancel_requested`.
   * Returns 409 `{ error: "run_terminal" }` if run is already completed/failed/cancelled.
   */
  async cancelRun(params: CancelRunParams): Promise<CancelRunResponse> {
    return invoke<CancelRunResponse>('orchestration_cancel_run_control', { ...params });
  },
};
