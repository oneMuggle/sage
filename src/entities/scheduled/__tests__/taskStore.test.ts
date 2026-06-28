import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/api/scheduledClient', () => ({
  scheduledClient: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    runNow: vi.fn(),
  },
}));

import { scheduledClient } from '../../../shared/api/scheduledClient';
import { useScheduledTaskStore } from '../taskStore';

const client = scheduledClient as unknown as {
  list: ReturnType<typeof vi.fn>;
  create: ReturnType<typeof vi.fn>;
  update: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
  runNow: ReturnType<typeof vi.fn>;
};

const sampleTask = {
  id: 'task-1',
  name: 'Demo',
  type: 'recurring' as const,
  schedule: { kind: 'recurring' as const, cron: '0 8 * * *' },
  session_id: 's-1',
  content: 'go',
  enabled: true,
  created_at: 1_700_000_000_000,
  last_run: null,
  next_run: 1_700_000_000_000,
};

describe('useScheduledTaskStore', () => {
  beforeEach(() => {
    useScheduledTaskStore.setState({ tasks: [], loading: false, error: null });
    client.list.mockReset();
    client.create.mockReset();
    client.update.mockReset();
    client.delete.mockReset();
    client.runNow.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('starts empty', () => {
    expect(useScheduledTaskStore.getState().tasks).toEqual([]);
  });

  it('load() fetches and stores tasks', async () => {
    client.list.mockResolvedValueOnce([sampleTask]);
    await useScheduledTaskStore.getState().load();
    expect(useScheduledTaskStore.getState().tasks).toEqual([sampleTask]);
    expect(useScheduledTaskStore.getState().loading).toBe(false);
  });

  it('load() sets error string on failure and clears tasks', async () => {
    client.list.mockRejectedValueOnce(new Error('boom'));
    await useScheduledTaskStore.getState().load();
    expect(useScheduledTaskStore.getState().error).toBe('boom');
    expect(useScheduledTaskStore.getState().tasks).toEqual([]);
  });

  it('create() appends returned task', async () => {
    client.create.mockResolvedValueOnce({ ...sampleTask, id: 'task-2' });
    await useScheduledTaskStore.getState().create({
      name: 'New',
      type: 'recurring',
      schedule: { kind: 'recurring', cron: '0 8 * * *' },
      session_id: 's-1',
      content: 'hi',
    });
    const ids = useScheduledTaskStore.getState().tasks.map((t) => t.id);
    expect(ids).toContain('task-2');
  });

  it('update() replaces task by id', async () => {
    client.list.mockResolvedValueOnce([sampleTask]);
    await useScheduledTaskStore.getState().load();
    const updated = { ...sampleTask, enabled: false };
    client.update.mockResolvedValueOnce(updated);
    await useScheduledTaskStore.getState().update('task-1', { enabled: false });
    expect(useScheduledTaskStore.getState().tasks[0].enabled).toBe(false);
  });

  it('delete() removes task by id', async () => {
    client.list.mockResolvedValueOnce([sampleTask]);
    await useScheduledTaskStore.getState().load();
    client.delete.mockResolvedValueOnce(undefined);
    await useScheduledTaskStore.getState().delete('task-1');
    expect(useScheduledTaskStore.getState().tasks).toEqual([]);
  });

  it('delete() surfaces error and keeps state on failure', async () => {
    client.list.mockResolvedValueOnce([sampleTask]);
    await useScheduledTaskStore.getState().load();
    client.delete.mockRejectedValueOnce(new Error('nope'));
    await expect(useScheduledTaskStore.getState().delete('task-1')).rejects.toThrow('nope');
    expect(useScheduledTaskStore.getState().error).toBe('nope');
    expect(useScheduledTaskStore.getState().tasks).toHaveLength(1);
  });
});
