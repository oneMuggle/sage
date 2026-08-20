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
import type { Message } from '../store';
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

describe('loadMessages local history merge', () => {
  beforeEach(() => {
    mockInvoke.mockReset();
    useStore.setState({ sessions: [], messages: [], currentSessionId: null });
  });

  it('preserves optimistic messages when backend history is empty', async () => {
    const localUser: Message = {
      id: 'local-user',
      session_id: 'session-1',
      role: 'user',
      content: '仍在发送的问题',
      created_at: 1_000,
    };
    const localAssistant: Message = {
      id: 'local-assistant',
      session_id: 'session-1',
      role: 'assistant',
      content: '🤔 思考中…',
      created_at: 1_001,
    };
    useStore.setState({ currentSessionId: 'session-1', messages: [localUser, localAssistant] });
    mockInvoke.mockResolvedValueOnce([]);

    await useStore.getState().loadMessages('session-1');

    expect(useStore.getState().messages).toEqual([localUser, localAssistant]);
  });

  it('prefers backend duplicates, isolates sessions, and stably sorts merged messages', async () => {
    const localUser: Message = {
      id: 'local-user',
      session_id: 'session-1',
      role: 'user',
      content: '仍在发送的问题',
      created_at: 1_000,
    };
    const localAssistant: Message = {
      id: 'assistant-1',
      session_id: 'session-1',
      role: 'assistant',
      content: '🤔 思考中…',
      created_at: 1_001,
    };
    const otherSessionMessage: Message = {
      id: 'other-session',
      session_id: 'session-2',
      role: 'user',
      content: '不应显示',
      created_at: 999,
    };
    const historyA: Message = {
      id: 'history-a',
      session_id: 'session-1',
      role: 'user',
      content: '第一条历史消息',
      created_at: 1_001,
    };
    const historyB: Message = {
      id: 'history-b',
      session_id: 'session-1',
      role: 'system',
      content: '第二条历史消息',
      created_at: 1_001,
    };
    const backendAssistant: Message = {
      ...localAssistant,
      content: '最终回复',
    };
    useStore.setState({
      currentSessionId: 'session-1',
      messages: [otherSessionMessage, localUser, localAssistant],
    });
    mockInvoke.mockResolvedValueOnce([historyB, backendAssistant, historyA]);

    await useStore.getState().loadMessages('session-1');

    expect(useStore.getState().messages).toEqual([localUser, historyB, backendAssistant, historyA]);
    expect(useStore.getState().messages.filter(({ id }) => id === 'assistant-1')).toHaveLength(1);
    expect(useStore.getState().messages.some(({ id }) => id === 'other-session')).toBe(false);
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
