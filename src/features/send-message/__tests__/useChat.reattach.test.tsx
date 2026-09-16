import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_SETTINGS } from '../../../entities/setting/types';
import type { AgentEvent } from '../../../shared/api';
import { chatApi, useStore } from '../../../shared/lib/store';
import { selectSessionSlots, useChatStreamStore } from '../chatStreamStore';
import { cancelSessionStream, useChat } from '../useChat';

vi.mock('../../manage-settings/useSettings', () => ({
  useSettings: () => ({ settings: DEFAULT_SETTINGS }),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

type Handlers = Parameters<typeof chatApi.listenStream>[1];
let handlers: Handlers;
let sid: string;
const cancel = vi.fn();
const loadMessages = vi.fn().mockResolvedValue(undefined);
const loadSessions = vi.fn().mockResolvedValue(undefined);
const slots = () => selectSessionSlots(useChatStreamStore.getState(), sid);
const emit = (event: Partial<AgentEvent>) => handlers.onEvent(event as AgentEvent);

beforeEach(() => {
  sid = crypto.randomUUID();
  cancel.mockClear();
  loadMessages.mockClear();
  loadSessions.mockClear();
  useStore.setState({
    currentSessionId: sid,
    messages: [],
    sessions: [],
    loadMessages,
    loadSessions,
  });
  useChatStreamStore.getState().resetAll();
  vi.spyOn(chatApi, 'activeStream').mockResolvedValue('stream-' + sid);
  vi.spyOn(chatApi, 'interrupt').mockResolvedValue(undefined);
  vi.spyOn(chatApi, 'listenStream').mockImplementation(async (_id, h) => {
    handlers = h;
    return { cancel };
  });
});

afterEach(async () => {
  await act(async () => {
    await cancelSessionStream(sid);
  });
  vi.restoreAllMocks();
  useChatStreamStore.getState().resetAll();
});

describe('reattach ownership and teardown', () => {
  it('reserves before lookup across hook instances, and applies deltas once', async () => {
    const probe = deferred<string | null>();
    vi.mocked(chatApi.activeStream).mockReturnValueOnce(probe.promise);
    const a = renderHook(() => useChat());
    const b = renderHook(() => useChat());
    await act(async () => {
      const first = a.result.current.reattachActiveStream(sid);
      await b.result.current.reattachActiveStream(sid);
      expect(chatApi.activeStream).toHaveBeenCalledTimes(1);
      expect(a.result.current.isLoading).toBe(false);
      probe.resolve('stream-one');
      await first;
    });
    expect(chatApi.listenStream).toHaveBeenCalledTimes(1);
    expect(useStore.getState().messages).toHaveLength(1);
    act(() => {
      emit({ state: 'content_delta', content: 'a' });
      emit({ state: 'content_delta', content: 'b' });
      emit({ state: 'reasoning_delta', reasoning: 'x' });
      emit({ state: 'reasoning_delta', reasoning: 'y' });
    });
    expect(slots().streaming?.content).toBe('ab');
    expect(slots().streaming?.reasoning).toBe('xy');
    act(() => emit({ state: 'reasoning_final', reasoning: 'final thought' }));
    expect(slots().streaming?.reasoning).toBe('final thought');
    act(() => {
      emit({ state: 'done', content: 'authoritative' });
      handlers.onDone?.();
      handlers.onError?.(new Error('late'));
    });
    expect(useStore.getState().messages[0].content).toBe('authoritative');
    expect(loadMessages).toHaveBeenCalledTimes(1);
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(slots().streaming).toBeNull();
  });

  it('remount keeps the live handle and can cancel it from the new hook', async () => {
    const first = renderHook(() => useChat());
    await act(async () => {
      await first.result.current.reattachActiveStream(sid);
    });
    first.unmount();
    const second = renderHook(() => useChat());
    expect(second.result.current.isLoading).toBe(true);
    await act(async () => {
      await second.result.current.reattachActiveStream(sid);
      await second.result.current.interrupt();
    });
    expect(chatApi.listenStream).toHaveBeenCalledTimes(1);
    expect(chatApi.interrupt).toHaveBeenCalledWith('stream-' + sid, sid);
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(second.result.current.isLoading).toBe(false);
  });

  it('cancellation before listener resolution disposes the late handle', async () => {
    const subscription = deferred<{ cancel: () => void }>();
    vi.mocked(chatApi.listenStream).mockImplementationOnce((_id, h) => {
      handlers = h;
      return subscription.promise;
    });
    const hook = renderHook(() => useChat());
    let pending!: Promise<void>;
    await act(async () => {
      pending = hook.result.current.reattachActiveStream(sid);
      await Promise.resolve();
    });
    await act(async () => {
      await cancelSessionStream(sid);
    });
    await act(async () => {
      subscription.resolve({ cancel });
      await pending;
      emit({ state: 'content_delta', content: 'late' });
    });
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(slots().streaming).toBeNull();
    expect(loadMessages).toHaveBeenCalledTimes(1);
  });

  it('cancellation while lookup is pending never creates a late placeholder', async () => {
    const probe = deferred<string | null>();
    vi.mocked(chatApi.activeStream).mockReturnValueOnce(probe.promise);
    const hook = renderHook(() => useChat());
    await act(async () => {
      const pending = hook.result.current.reattachActiveStream(sid);
      await cancelSessionStream(sid);
      probe.resolve('late-stream');
      await pending;
    });
    expect(chatApi.interrupt).toHaveBeenCalledWith(undefined, sid);
    expect(chatApi.listenStream).not.toHaveBeenCalled();
    expect(useStore.getState().messages).toHaveLength(0);
    expect(hook.result.current.isLoading).toBe(false);
  });

  it.each(['lookup failure', 'idle session', 'listen failure'])(
    'releases reservation after %s',
    async (failure) => {
      if (failure === 'lookup failure')
        vi.mocked(chatApi.activeStream).mockRejectedValueOnce(new Error('offline'));
      if (failure === 'idle session') vi.mocked(chatApi.activeStream).mockResolvedValueOnce(null);
      if (failure === 'listen failure')
        vi.mocked(chatApi.listenStream).mockRejectedValueOnce(new Error('offline'));
      const hook = renderHook(() => useChat());
      await act(async () => {
        await hook.result.current.reattachActiveStream(sid);
        await hook.result.current.reattachActiveStream(sid);
      });
      expect(chatApi.activeStream).toHaveBeenCalledTimes(2);
      expect(slots().streaming).not.toBeNull();
    },
  );

  it('terminal replay before subscription resolves cleans up exactly once', async () => {
    vi.mocked(chatApi.listenStream).mockImplementationOnce(async (_id, h) => {
      h.onEvent({ state: 'done', content: 'final' } as AgentEvent);
      h.onDone?.();
      return { cancel };
    });
    const hook = renderHook(() => useChat());
    await act(async () => {
      await hook.result.current.reattachActiveStream(sid);
    });
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(loadMessages).toHaveBeenCalledTimes(1);
    expect(slots().streaming).toBeNull();
  });

  it('without any frontend handle, cancellation still targets the requested session', async () => {
    expect(await cancelSessionStream(sid)).toBe(false);
    expect(chatApi.interrupt).toHaveBeenCalledWith(undefined, sid);
  });
});
