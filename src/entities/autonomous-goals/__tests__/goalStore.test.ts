import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const mockListGoals = vi.fn();
const mockCreateGoal = vi.fn();
const mockUpdateGoal = vi.fn();
const mockDeleteGoal = vi.fn();
const mockStartGoal = vi.fn();
const mockPauseGoal = vi.fn();
const mockCancelGoal = vi.fn();
const mockGetGoal = vi.fn();

vi.mock('../goalApi', () => ({
  listGoals: (...args: unknown[]) => mockListGoals(...args),
  createGoal: (...args: unknown[]) => mockCreateGoal(...args),
  updateGoal: (...args: unknown[]) => mockUpdateGoal(...args),
  deleteGoal: (...args: unknown[]) => mockDeleteGoal(...args),
  startGoal: (...args: unknown[]) => mockStartGoal(...args),
  pauseGoal: (...args: unknown[]) => mockPauseGoal(...args),
  cancelGoal: (...args: unknown[]) => mockCancelGoal(...args),
  getGoal: (...args: unknown[]) => mockGetGoal(...args),
}));

import { formatGoalStoreJson, formatGoalStoreSummary, useGoalStore } from '../goalStore';
import type { Goal } from '../types';

const sampleGoal: Goal = {
  id: 'g-1',
  name: 'Goal 1',
  description: 'Desc',
  status: 'pending',
  session_id: null,
  time_window: {
    off_peak_start: '22:00',
    off_peak_end: '08:00',
    weekends_off_peak: true,
    holidays: [],
    min_pricing_tier: 'standard',
    timezone: 'Asia/Shanghai',
  },
  budget: {
    max_rounds: 5,
    max_hours: 2,
    max_tokens: 10000,
    stop_on_failure: false,
  },
  checkpoints: [],
  current_round: 0,
  created_at: '2026-10-21T00:00:00Z',
  started_at: null,
  completed_at: null,
  total_tokens_used: 0,
  completion_percentage: 0,
  degradation_level: 'none',
  last_error: null,
  trigger_mode: 'immediate',
  execution_conditions: [],
};

describe('useGoalStore', () => {
  beforeEach(() => {
    useGoalStore.setState({
      goals: [],
      total: 0,
      loading: false,
      error: null,
      statusFilter: null,
    });
    vi.clearAllMocks();
  });

  it('loads, creates, updates, transitions, and deletes goals', async () => {
    mockListGoals.mockResolvedValueOnce({ items: [sampleGoal], total: 1, limit: 50, offset: 0 });
    await useGoalStore.getState().load();
    expect(useGoalStore.getState().goals).toHaveLength(1);

    const g2 = { ...sampleGoal, id: 'g-2', name: 'Goal 2' };
    mockCreateGoal.mockResolvedValueOnce(g2);
    await useGoalStore.getState().create({ name: 'Goal 2', description: 'Desc' });
    expect(useGoalStore.getState().goals).toHaveLength(2);

    mockUpdateGoal.mockResolvedValueOnce({ ...g2, name: 'Goal 2 Updated' });
    await useGoalStore.getState().update('g-2', { name: 'Goal 2 Updated' });

    mockStartGoal.mockResolvedValueOnce({ ...g2, status: 'running' });
    await useGoalStore.getState().start('g-2');

    mockPauseGoal.mockResolvedValueOnce({ ...g2, status: 'paused' });
    await useGoalStore.getState().pause('g-2');

    mockCancelGoal.mockResolvedValueOnce({ ...g2, status: 'cancelled' });
    await useGoalStore.getState().cancel('g-2');

    mockGetGoal.mockResolvedValueOnce({ ...g2, completion_percentage: 50 });
    await useGoalStore.getState().refreshOne('g-2');

    mockDeleteGoal.mockResolvedValueOnce(undefined);
    await useGoalStore.getState().delete('g-2');
    expect(useGoalStore.getState().goals).toHaveLength(1);
  });

  it('formats goal store summary and JSON (Phase P120)', () => {
    useGoalStore.setState({
      goals: [sampleGoal],
      total: 1,
      loading: false,
      error: null,
      statusFilter: 'pending',
    });
    expect(formatGoalStoreSummary()).toBe(
      'goals=1/1 · filter=pending · loading=false · error=none',
    );
    expect(JSON.parse(formatGoalStoreJson())).toEqual({
      goalCount: 1,
      total: 1,
      statusFilter: 'pending',
      loading: false,
      error: null,
    });
  });
});
