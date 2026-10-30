import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  process: vi.fn(),
  status: vi.fn(),
  tasks: vi.fn(),
}));

vi.mock('../../../shared/api-client/wiki', () => ({
  queueAddTask: vi.fn(),
  queueCancelTask: vi.fn(),
  queueRetryTask: vi.fn(),
  queueClearTasks: vi.fn(),
  queueGetStatus: api.status,
  queueListTasks: api.tasks,
  queueProcess: api.process,
}));

import { formatQueueStoreJson, formatQueueStoreSummary, useQueueStore } from '../queue-store';

beforeEach(() => {
  vi.clearAllMocks();
  useQueueStore.getState().reset();
});

describe('processQueue', () => {
  it('calls the backend then refreshes status and tasks', async () => {
    api.process.mockResolvedValue({
      processed: [{ task_id: 't1', status: 'completed', wiki_page_path: 'wiki/sources/a.md' }],
      remaining: { pending: 0, processing: 0, completed: 1, failed: 0, cancelled: 0 },
    });
    api.status.mockResolvedValue({
      pending: 0,
      processing: 0,
      completed: 1,
      failed: 0,
      cancelled: 0,
    });
    api.tasks.mockResolvedValue({ tasks: [] });

    const result = await useQueueStore.getState().processQueue('/proj', 5);

    expect(api.process).toHaveBeenCalledWith('/proj', 5);
    expect(api.status).toHaveBeenCalledWith('/proj');
    expect(api.tasks).toHaveBeenCalledWith('/proj', undefined);
    expect(result?.processed[0].status).toBe('completed');
    expect(useQueueStore.getState().loading).toBe(false);
  });

  it('surfaces backend errors without throwing', async () => {
    api.process.mockRejectedValue(new Error('boom'));

    const result = await useQueueStore.getState().processQueue('/proj', 1);

    expect(result).toBeNull();
    expect(useQueueStore.getState().error).toBe('boom');
    expect(useQueueStore.getState().loading).toBe(false);
  });
});

describe('wiki queue-store audit helpers', () => {
  it('resets store state and formats queue summary', () => {
    useQueueStore.getState().reset();
    expect(
      formatQueueStoreSummary({ pending: 2, processing: 1, completed: 5, failed: 0 }, 8, false),
    ).toBe('tasks=8 · pending=2 · processing=1 · completed=5 · failed=0 · loading=false');
  });

  it('serializes queue store audit JSON', () => {
    expect(
      JSON.parse(
        formatQueueStoreJson(
          { pending: 1, processing: 0, completed: 3, failed: 1, cancelled: 2 },
          7,
          true,
        ),
      ),
    ).toEqual({
      taskCount: 7,
      pending: 1,
      processing: 0,
      completed: 3,
      failed: 1,
      cancelled: 2,
      loading: true,
    });
  });
});
