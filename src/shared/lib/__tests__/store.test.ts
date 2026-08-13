import { beforeEach, describe, expect, it, vi } from 'vitest';

const { mockLoad, mockSave } = vi.hoisted(() => ({
  mockLoad: vi.fn(),
  mockSave: vi.fn(),
}));
vi.mock('../../../entities/session/storage', () => ({
  loadCurrentSessionId: (...args: unknown[]) => mockLoad(...args),
  saveCurrentSessionId: (...args: unknown[]) => mockSave(...args),
}));

const { mockInvoke } = vi.hoisted(() => ({ mockInvoke: vi.fn() }));
vi.mock('../../api/desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { clientLogger } from '../../log/client';
import { useStore } from '../store';

describe('useStore currentSessionId async', () => {
  beforeEach(() => {
    localStorage.clear();
    mockLoad.mockReset();
    mockSave.mockReset();
    useStore.setState({ currentSessionId: null });
  });

  it('setCurrentSessionId 调 saveCurrentSessionId 异步', async () => {
    mockSave.mockResolvedValue(undefined);
    useStore.getState().setCurrentSessionId('abc-123');
    expect(useStore.getState().currentSessionId).toBe('abc-123');
    await vi.waitFor(() => expect(mockSave).toHaveBeenCalledWith('abc-123'));
  });

  it('setCurrentSessionId(null) 同步清空', () => {
    useStore.setState({ currentSessionId: 'old' });
    useStore.getState().setCurrentSessionId(null);
    expect(useStore.getState().currentSessionId).toBeNull();
  });
});

describe('store failure logging', () => {
  beforeEach(() => {
    mockInvoke.mockReset();
    useStore.setState({ sessions: [], messages: [], currentSessionId: null });
  });

  it.each([
    ['loadSessions', 'store.loadSessions failed'],
    ['createSession', 'store.createSession failed'],
    ['deleteSession', 'store.deleteSession failed'],
    ['loadMessages', 'store.loadMessages failed'],
  ])('%s failure logs via clientLogger.error', async (action, msg) => {
    mockInvoke.mockRejectedValue(new Error('boom'));
    const spy = vi.spyOn(clientLogger, 'error').mockImplementation(() => {});
    const st = useStore.getState() as unknown as Record<string, (arg?: string) => Promise<unknown>>;
    await (st[action] as (arg?: string) => Promise<unknown>)('sess-1').catch(() => {});
    expect(spy).toHaveBeenCalledWith(msg, { error: 'Error: boom' });
    spy.mockRestore();
  });
});
