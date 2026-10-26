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

// 2026-10-26: 动态 watchdog 超时测试 — 验证 config.watchdogSilenceMs 生效,
// 以及 heartbeat 事件能喂狗防止误杀。
describe.each(['create', 'reattach'] as const)('%s dynamic watchdog', (mode) => {
  const startWithConfig = (
    handlers: Parameters<typeof chatApi.listenStream>[1],
    config?: { watchdogSilenceMs?: number },
  ) =>
    mode === 'create'
      ? chatApi.chatStream('11111111-2222-3333-4444-555555555555', 'hello', handlers, config)
      : chatApi.listenStream('stream', handlers, config);

  it('default watchdog fires at 180s with "180 秒无任何事件" error', async () => {
    const unlisten = vi.fn();
    listen.mockImplementationOnce(async (_name, _cb) => unlisten);
    const onError = vi.fn();
    const onDone = vi.fn();
    await startWithConfig({ onEvent: vi.fn(), onError, onDone });

    // 前进 179s → 还没触发
    vi.advanceTimersByTime(179_000);
    expect(onError).not.toHaveBeenCalled();

    // 前进 1s → 达到 180s 阈值
    vi.advanceTimersByTime(1_000);
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0].message).toContain('180 秒无任何事件');
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it('custom watchdogSilenceMs=60_000 fires at 60s', async () => {
    const unlisten = vi.fn();
    listen.mockImplementationOnce(async (_name, _cb) => unlisten);
    const onError = vi.fn();
    const onDone = vi.fn();
    await startWithConfig({ onEvent: vi.fn(), onError, onDone }, { watchdogSilenceMs: 60_000 });

    vi.advanceTimersByTime(59_000);
    expect(onError).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1_000);
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0].message).toContain('60 秒无任何事件');
  });

  it('heartbeat events feed the watchdog and prevent timeout', async () => {
    let emit!: (event: { payload: Partial<AgentEvent> }) => void;
    const unlisten = vi.fn();
    listen.mockImplementationOnce(async (_name, cb) => {
      emit = cb;
      return unlisten;
    });
    const onError = vi.fn();
    const onDone = vi.fn();
    await startWithConfig({ onEvent: vi.fn(), onError, onDone }, { watchdogSilenceMs: 30_000 });

    // 前进 25s → 还没触发(阈值 30s)
    vi.advanceTimersByTime(25_000);
    expect(onError).not.toHaveBeenCalled();

    // heartbeat 到达 → 喂狗,重置计时器
    emit({ payload: { state: 'heartbeat' } as AgentEvent });
    expect(onError).not.toHaveBeenCalled();

    // 再前进 25s → 还没触发(从 heartbeat 重新计时)
    vi.advanceTimersByTime(25_000);
    expect(onError).not.toHaveBeenCalled();

    // 再前进 5s → 达到 30s → 触发
    vi.advanceTimersByTime(5_000);
    expect(onError).toHaveBeenCalledTimes(1);
  });
});
