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
import { type Message, useStore } from '../store';

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

describe('loadMessages merge behavior', () => {
  beforeEach(() => {
    mockInvoke.mockReset();
    useStore.setState({ sessions: [], messages: [], currentSessionId: null });
  });

  it('preserves backend input order when timestamps are unsorted', async () => {
    const first: Message = {
      id: 'history-first', session_id: 'session-1', role: 'user', content: '第一条', created_at: 2_000,
    };
    const second: Message = {
      id: 'history-second', session_id: 'session-1', role: 'assistant', content: '第二条', created_at: 1_000,
    };
    mockInvoke.mockResolvedValueOnce([first, second]);

    await useStore.getState().loadMessages('session-1');

    expect(useStore.getState().messages).toEqual([first, second]);
  });

  it('merges messages added while loading from the latest store state', async () => {
    const localMessage: Message = {
      id: 'local-during-load', session_id: 'session-1', role: 'user', content: '加载期间新增', created_at: 1_000,
    };
    let resolveInvoke: (messages: Message[]) => void = () => {};
    mockInvoke.mockReturnValueOnce(new Promise<Message[]>((resolve) => { resolveInvoke = resolve; }));

    const loading = useStore.getState().loadMessages('session-1');
    useStore.getState().addMessage(localMessage);
    resolveInvoke([]);
    await loading;

    expect(useStore.getState().messages).toEqual([localMessage]);
  });


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
