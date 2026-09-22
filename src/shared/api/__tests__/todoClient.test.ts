import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../desktopInvoke', () => ({
  invoke: vi.fn(),
}));

import { invoke } from '../desktopInvoke';
import { todoClient } from '../todoClient';

const invokeMock = invoke as unknown as ReturnType<typeof vi.fn>;

describe('todoClient', () => {
  afterEach(() => {
    invokeMock.mockReset();
  });

  it('list() forwards params to todo_list', async () => {
    invokeMock.mockResolvedValueOnce({ items: [], total: 0, limit: 50, offset: 0 });
    const result = await todoClient.list({ status: 'pending', sort_by: 'priority' });
    expect(invokeMock).toHaveBeenCalledWith('todo_list', {
      status: 'pending',
      sort_by: 'priority',
    });
    expect(result.total).toBe(0);
  });

  it('list() with no params sends an empty object', async () => {
    invokeMock.mockResolvedValueOnce({ items: [], total: 0, limit: 50, offset: 0 });
    await todoClient.list();
    expect(invokeMock).toHaveBeenCalledWith('todo_list', {});
  });

  it('create() posts the input fields to todo_create', async () => {
    invokeMock.mockResolvedValueOnce({ id: 1, title: 'x', status: 'pending' });
    await todoClient.create({ title: 'x', priority: 'high' });
    expect(invokeMock.mock.calls[0][0]).toBe('todo_create');
    expect(invokeMock.mock.calls[0][1]).toEqual({ title: 'x', priority: 'high' });
  });

  it('update() sends id and changes to todo_update', async () => {
    invokeMock.mockResolvedValueOnce({ id: 7, title: 'y' });
    await todoClient.update(7, { title: 'y' });
    expect(invokeMock.mock.calls[0][0]).toBe('todo_update');
    expect(invokeMock.mock.calls[0][1]).toEqual({ id: 7, title: 'y' });
  });

  it('get / complete / cancel / delete / summary / stats map to their channels', async () => {
    invokeMock.mockResolvedValue({ id: 1 });
    await todoClient.get(1);
    expect(invokeMock.mock.calls[0][0]).toBe('todo_get');
    await todoClient.complete(1);
    expect(invokeMock.mock.calls[1][0]).toBe('todo_complete');
    await todoClient.cancel(1);
    expect(invokeMock.mock.calls[2][0]).toBe('todo_cancel');
    invokeMock.mockResolvedValue(undefined);
    await todoClient.delete(1);
    expect(invokeMock.mock.calls[3][0]).toBe('todo_delete');
    invokeMock.mockResolvedValue({ overdue: [] });
    await todoClient.summary();
    expect(invokeMock.mock.calls[4][0]).toBe('todo_summary');
    invokeMock.mockResolvedValue({ total: 0 });
    await todoClient.stats();
    expect(invokeMock.mock.calls[5][0]).toBe('todo_stats');
  });

  it('propagates invoke failures', async () => {
    invokeMock.mockRejectedValueOnce(new Error('boom'));
    await expect(todoClient.list()).rejects.toThrow('boom');
  });
});
