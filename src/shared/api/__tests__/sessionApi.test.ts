/**
 * r84: sessionApi 单元测试——核心 CRUD + pin/archive/rename。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

vi.mock('../utils', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    handleApiError: (error: unknown) => error,
    withRetry: async (fn: () => Promise<unknown>) => fn(),
  };
});

import { sessionApi } from '../sessionApi';

const SID = '12345678-1234-1234-1234-123456789abc';
const SESSION = { id: SID, title: 'test', created_at: 1, updated_at: 1 };

beforeEach(() => { mockInvoke.mockReset(); });

describe('sessionApi', () => {
  it('create() passes title', async () => {
    mockInvoke.mockResolvedValueOnce(SESSION);
    const r = await sessionApi.create('新对话');
    expect(mockInvoke).toHaveBeenCalledWith('create_session', expect.objectContaining({ title: '新对话' }));
    expect(r).toEqual(SESSION);
  });

  it('list() invokes list_sessions', async () => {
    mockInvoke.mockResolvedValueOnce([SESSION]);
    const r = await sessionApi.list();
    expect(mockInvoke).toHaveBeenCalledWith('list_sessions');
    expect(r).toEqual([SESSION]);
  });

  it('get() passes id', async () => {
    mockInvoke.mockResolvedValueOnce(SESSION);
    await sessionApi.get(SID);
    expect(mockInvoke).toHaveBeenCalledWith('get_session', expect.objectContaining({ id: SID }));
  });

  it('get() rejects invalid session id', async () => {
    await expect(sessionApi.get('short')).rejects.toThrow('无效的会话ID格式');
  });

  it('delete() passes id', async () => {
    mockInvoke.mockResolvedValueOnce(undefined);
    await sessionApi.delete(SID);
    expect(mockInvoke).toHaveBeenCalledWith('delete_session', expect.objectContaining({ id: SID }));
  });

  it('getMessages() passes sessionId', async () => {
    mockInvoke.mockResolvedValueOnce([]);
    await sessionApi.getMessages(SID);
    expect(mockInvoke).toHaveBeenCalledWith('get_messages', expect.objectContaining({ sessionId: SID }));
  });

  it('rename() passes id and title', async () => {
    mockInvoke.mockResolvedValueOnce(SESSION);
    await sessionApi.rename(SID, 'renamed');
    expect(mockInvoke).toHaveBeenCalledWith('session_update', expect.objectContaining({ sessionId: SID, title: 'renamed' }));
  });

  it('setPinned() passes id and pinned', async () => {
    mockInvoke.mockResolvedValueOnce(SESSION);
    await sessionApi.setPinned(SID, true);
    expect(mockInvoke).toHaveBeenCalledWith('session_update', expect.objectContaining({ sessionId: SID, isPinned: true }));
  });

  it('setArchived() passes id and archived', async () => {
    mockInvoke.mockResolvedValueOnce(SESSION);
    await sessionApi.setArchived(SID, true);
    expect(mockInvoke).toHaveBeenCalledWith('session_update', expect.objectContaining({ sessionId: SID, isArchived: true }));
  });

  it('propagates invoke errors', async () => {
    mockInvoke.mockRejectedValueOnce(new Error('session not found'));
    await expect(sessionApi.get('12345678-1234-1234-1234-123456789abc')).rejects.toThrow('session not found');
  });
});