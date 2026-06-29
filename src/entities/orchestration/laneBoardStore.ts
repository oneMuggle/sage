/**
 * LaneBoardStore - Zustand store for multi-agent orchestration board.
 *
 * Manages the three-column lane board view (active / blocked / finished)
 * with immutable updates and immutable state transitions.
 */
import { create } from 'zustand';

import { orchestrationClient } from '../../shared/api/orchestrationClient';
import type { Lane, LaneBoardGroup, LaneEvent, LaneStatus } from '../../shared/api/types';

interface LaneBoardState {
  lanes: Lane[];
  loading: boolean;
  error: string | null;
  teamIdFilter: string | null;
  load: (teamId?: string) => Promise<void>;
  refresh: () => Promise<void>;
  cancel: (laneId: string, reason?: string) => Promise<void>;
  applyEvent: (event: LaneEvent) => void;
  computeBoard: () => LaneBoardGroup;
}

const ACTIVE_STATUSES: ReadonlySet<LaneStatus> = new Set(['created', 'ready', 'running']);

const BLOCKED_STATUSES: ReadonlySet<LaneStatus> = new Set(['blocked']);

const FINISHED_STATUSES: ReadonlySet<LaneStatus> = new Set([
  'succeeded',
  'failed',
  'stopped',
  'cancelled',
]);

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

function groupLanes(lanes: readonly Lane[]): LaneBoardGroup {
  const active: Lane[] = [];
  const blocked: Lane[] = [];
  const finished: Lane[] = [];

  for (const lane of lanes) {
    if (ACTIVE_STATUSES.has(lane.status)) {
      active.push(lane);
    } else if (BLOCKED_STATUSES.has(lane.status)) {
      blocked.push(lane);
    } else if (FINISHED_STATUSES.has(lane.status)) {
      finished.push(lane);
    }
  }

  return { active, blocked, finished };
}

export const useLaneBoardStore = create<LaneBoardState>((set, get) => ({
  lanes: [],
  loading: false,
  error: null,
  teamIdFilter: null,

  async load(teamId?: string) {
    set({ loading: true, error: null, teamIdFilter: teamId ?? null });
    try {
      const params: { team_id?: string } = {};
      if (teamId) params.team_id = teamId;
      const lanes = await orchestrationClient.listLanes(params);
      set({ lanes, loading: false });
    } catch (error: unknown) {
      set({ lanes: [], loading: false, error: getErrorMessage(error) });
    }
  },

  async refresh() {
    const { teamIdFilter } = get();
    const params: { team_id?: string } = {};
    if (teamIdFilter) params.team_id = teamIdFilter;
    try {
      const lanes = await orchestrationClient.listLanes(params);
      set({ lanes, error: null });
    } catch (error: unknown) {
      set({ error: getErrorMessage(error) });
    }
  },

  async cancel(laneId: string, reason: string = 'user_cancelled') {
    try {
      const updated = await orchestrationClient.cancelLane(laneId, reason);
      set({
        lanes: get().lanes.map((l) => (l.lane_id === laneId ? updated : l)),
      });
    } catch (error: unknown) {
      set({ error: getErrorMessage(error) });
      throw error;
    }
  },

  applyEvent(event: LaneEvent) {
    const { lanes } = get();
    const index = lanes.findIndex((l) => l.lane_id === event.lane_id);
    if (index === -1) {
      void get().refresh();
      return;
    }

    const existing = lanes[index];
    if (!existing) return;

    const statusFromEvent: Partial<Record<LaneEvent['event_type'], LaneStatus>> = {
      'lane.started': 'created',
      'lane.ready': 'ready',
      'lane.running': 'running',
      'lane.blocked': 'blocked',
      'lane.succeeded': 'succeeded',
      'lane.failed': 'failed',
      'lane.stopped': 'stopped',
    };

    const newStatus = statusFromEvent[event.event_type];
    if (!newStatus) return;

    const updated: Lane = {
      ...existing,
      status: newStatus,
      completed_at:
        newStatus === 'succeeded' || newStatus === 'failed' || newStatus === 'stopped'
          ? event.timestamp
          : existing.completed_at,
      started_at:
        newStatus === 'running' && existing.started_at == null
          ? event.timestamp
          : existing.started_at,
    };

    set({
      lanes: lanes.map((l) => (l.lane_id === event.lane_id ? updated : l)),
    });
  },

  computeBoard(): LaneBoardGroup {
    return groupLanes(get().lanes);
  },
}));
