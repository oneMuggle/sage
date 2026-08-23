/**
 * IPC client for multi-agent orchestration (Phase 4 + M5).
 *
 * Translates to backend HTTP via Electron preload:
 *   orchestration_list_lanes       → GET    /api/v1/orchestration/lanes
 *   orchestration_get_lane        → GET    /api/v1/orchestration/lanes/{id}
 *   orchestration_list_lane_events → GET    /api/v1/orchestration/lanes/{id}/events
 *   orchestration_cancel_lane      → POST   /api/v1/orchestration/lanes/{id}/cancel
 *   orchestration_create_lane      → POST   /api/v1/orchestration/lanes (M5)
 *
 * All methods throw on IPC failure; callers should wrap in try/catch and
 * surface a toast on failure.
 */
import { invoke } from './desktopInvoke';
import type {
  CreateLanesResponse,
  Lane,
  LaneBoardSnapshot,
  LaneEvent,
  LaneStatus,
} from './types';

export interface ListLanesParams {
  status?: LaneStatus;
  team_id?: string;
  limit?: number;
}

export interface CreateLaneParams {
  goal: string;
  agent?: string;
}

export const orchestrationClient = {
  async listLanes(params: ListLanesParams = {}): Promise<Lane[]> {
    return invoke<Lane[]>('orchestration_list_lanes', { params });
  },

  /** M5: decompose a goal via the planner and create tasks + lanes. */
  async createLane(params: CreateLaneParams): Promise<CreateLanesResponse> {
    return invoke<CreateLanesResponse>('orchestration_create_lane', { ...params });
  },

  async getLane(laneId: string): Promise<Lane> {
    return invoke<Lane>('orchestration_get_lane', { lane_id: laneId });
  },

  async listLaneEvents(laneId: string): Promise<LaneEvent[]> {
    return invoke<LaneEvent[]>('orchestration_list_lane_events', { lane_id: laneId });
  },

  async cancelLane(laneId: string, reason: string = 'user_cancelled'): Promise<Lane> {
    return invoke<Lane>('orchestration_cancel_lane', {
      lane_id: laneId,
      reason,
    });
  },

  /** P2-5: LaneBoard 快照（freshness_summary；view 走投影协商）。 */
  async getBoard(view: 'ops_full' | 'ui_minimal' = 'ops_full'): Promise<LaneBoardSnapshot> {
    return invoke<LaneBoardSnapshot>('orchestration_board', { view });
  },
};
