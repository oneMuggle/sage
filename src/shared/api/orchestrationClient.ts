/**
 * IPC client for multi-agent orchestration (Phase 4).
 *
 * Translates to backend HTTP via Electron preload:
 *   orchestration_list_lanes       → GET    /api/v1/orchestration/lanes
 *   orchestration_get_lane        → GET    /api/v1/orchestration/lanes/{id}
 *   orchestration_list_lane_events → GET    /api/v1/orchestration/lanes/{id}/events
 *   orchestration_cancel_lane      → POST   /api/v1/orchestration/lanes/{id}/cancel
 *
 * All methods throw on IPC failure; callers should wrap in try/catch and
 * surface a toast on failure.
 */
import { invoke } from './desktopInvoke';
import type { Lane, LaneEvent, LaneStatus } from './types';

export interface ListLanesParams {
  status?: LaneStatus;
  team_id?: string;
  limit?: number;
}

export const orchestrationClient = {
  async listLanes(params: ListLanesParams = {}): Promise<Lane[]> {
    return invoke<Lane[]>('orchestration_list_lanes', { params });
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
};
