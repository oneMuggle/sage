import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockBackendRequest = vi.fn();
vi.mock('../../../shared/api/backendRequest', () => ({
  backendRequest: (...args: unknown[]) => mockBackendRequest(...args),
}));

import {
  cancelGoal,
  createGoal,
  deleteGoal,
  formatGoalListQueryJson,
  formatGoalListQuerySummary,
  generateCheckpoints,
  getExecutionReport,
  getGoal,
  listGoals,
  pauseGoal,
  startGoal,
  updateGoal,
} from '../goalApi';

describe('goalApi', () => {
  beforeEach(() => {
    mockBackendRequest.mockReset();
  });

  it('calls backendRequest for CRUD and lifecycle endpoints', async () => {
    mockBackendRequest.mockResolvedValue({});
    await listGoals('running', 10, 5);
    expect(mockBackendRequest).toHaveBeenLastCalledWith({
      method: 'GET',
      path: '/api/v1/goals?status=running&limit=10&offset=5',
    });

    await createGoal({ name: 'g1', description: 'd1' });
    expect(mockBackendRequest).toHaveBeenLastCalledWith({
      method: 'POST',
      path: '/api/v1/goals',
      body: { name: 'g1', description: 'd1' },
    });

    await getGoal('g1');
    await updateGoal('g1', { name: 'g2' });
    await deleteGoal('g1');
    await startGoal('g1');
    await pauseGoal('g1');
    await cancelGoal('g1');
    await getExecutionReport('g1');
    await generateCheckpoints('g1');
    expect(mockBackendRequest).toHaveBeenCalledTimes(10);
  });

  it('formats goal list query summary and JSON (Phase P120)', () => {
    expect(formatGoalListQuerySummary('pending', 20, 0)).toBe(
      'path=/api/v1/goals · status=pending · limit=20 · offset=0',
    );
    expect(JSON.parse(formatGoalListQueryJson('pending', 20, 0))).toEqual({
      basePath: '/api/v1/goals',
      status: 'pending',
      limit: 20,
      offset: 0,
    });
  });
});
