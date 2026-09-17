import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { chatApi } from '../chatApi';
import type { AgentEvent } from '../types';

const listen = vi.fn();
vi.mock('../desktopEvent', () => ({ listen: (...args: unknown[]) => listen(...args) }));
vi.mock('../desktopInvoke', () => ({ invoke: vi.fn().mockResolvedValue({ streamId: 'stream' }) }));


beforeEach(() => {
  vi.useFakeTimers();
  listen.mockReset();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe.each(['create', 'reattach'] as const)('%s subscription lifecycle', (mode) => {
  const start = (handlers: Parameters<typeof chatApi.listenStream>[1]) =>
    mode === 'create'
      ? chatApi.chatStream('11111111-2222-3333-4444-555555555555', 'hello', handlers)
      : chatApi.listenStream('stream', handlers);

  it('disposes subscription returned after a buffered terminal event and never rearms watchdog', async () => {
    const unlisten = vi.fn();
    const onDone = vi.fn();
    listen.mockImplementationOnce(async (_name, cb) => {
      cb({ payload: { state: 'done' } });
      cb({ payload: { state: 'done' } });
      return unlisten;
    });
    const onEvent = vi.fn();
    await start({ onEvent, onDone });
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(unlisten).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('cancel is terminal and idempotent even if the event bridge dispatches late events', async () => {
    let emit!: (event: { payload: Partial<AgentEvent> }) => void;
    const unlisten = vi.fn();
    listen.mockImplementationOnce(async (_name, cb) => {
      emit = cb;
      return unlisten;
    });
    const onEvent = vi.fn();
    const handle = await start({ onEvent });
    handle.cancel();
    handle.cancel();
    emit({ payload: { state: 'content_delta', content: 'late' } });
    expect(unlisten).toHaveBeenCalledTimes(1);
    expect(onEvent).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
});
