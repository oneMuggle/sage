import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../desktopInvoke', () => ({
  invoke: vi.fn(),
}));

import { invoke } from '../desktopInvoke';
import { scheduledClient } from '../scheduledClient';

const invokeMock = invoke as unknown as ReturnType<typeof vi.fn>;

describe('scheduledClient', () => {
  afterEach(() => {
    invokeMock.mockReset();
  });

  it('list() invokes scheduled_list_tasks and returns array', async () => {
    invokeMock.mockResolvedValueOnce([]);
    const result = await scheduledClient.list();
    expect(invokeMock).toHaveBeenCalledWith('scheduled_list_tasks', {});
    expect(result).toEqual([]);
  });

  it('create() posts scheduled_create_task payload', async () => {
    const fixture = {
      id: 'task-1',
      name: 'x',
      type: 'once' as const,
      schedule: { kind: 'once' as const, at: Date.now() + 60_000 },
      session_id: 's-1',
      content: 'hi',
      enabled: true,
      created_at: Date.now(),
    };
    invokeMock.mockResolvedValueOnce(fixture);
    await scheduledClient.create({
      name: 'x',
      type: 'once',
      schedule: { kind: 'once', at: Date.now() + 60_000 },
      session_id: 's-1',
      content: 'hi',
    });
    expect(invokeMock.mock.calls[0][0]).toBe('scheduled_create_task');
  });

  it('update() sends id and changes via invoke', async () => {
    invokeMock.mockResolvedValueOnce({});
    await scheduledClient.update('task-1', { enabled: false });
    expect(invokeMock.mock.calls[0][0]).toBe('scheduled_update_task');
    expect(invokeMock.mock.calls[0][1]).toEqual({ id: 'task-1', changes: { enabled: false } });
  });

  it('delete() sends id and resolves when invoke resolves', async () => {
    invokeMock.mockResolvedValueOnce(undefined);
    await scheduledClient.delete('task-1');
    expect(invokeMock.mock.calls[0][0]).toBe('scheduled_delete_task');
    expect(invokeMock.mock.calls[0][1]).toEqual({ id: 'task-1' });
  });

  it('runNow() invokes scheduled_run_task', async () => {
    invokeMock.mockResolvedValueOnce({});
    await scheduledClient.runNow('task-1');
    expect(invokeMock.mock.calls[0][0]).toBe('scheduled_run_task');
    expect(invokeMock.mock.calls[0][1]).toEqual({ id: 'task-1' });
  });

  it('propagates errors from invoke', async () => {
    invokeMock.mockRejectedValueOnce(new Error('boom'));
    await expect(scheduledClient.list()).rejects.toThrow('boom');
  });
});
