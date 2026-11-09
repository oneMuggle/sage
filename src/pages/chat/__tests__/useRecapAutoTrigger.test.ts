import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useRecapAutoTrigger } from '../useRecapAutoTrigger';

type FocusHandler = (payload: { awayMs: number }) => void;

function installListenMock() {
  const handlers = new Map<string, FocusHandler>();
  const unlistenFn = vi.fn();
  const listen = vi.fn(async (event: string, handler: FocusHandler) => {
    handlers.set(event, handler);
    return unlistenFn;
  });
  Object.defineProperty(window, 'electronAPI', {
    configurable: true,
    value: { listen },
  });
  return {
    listen,
    unlistenFn,
    fireFocus: (payload: { awayMs: number }) => handlers.get('app-focus')?.(payload),
  };
}

describe('useRecapAutoTrigger', () => {
  it('no-op when electronAPI is absent', () => {
    Object.defineProperty(window, 'electronAPI', { configurable: true, value: undefined });
    const onRecap = vi.fn();
    renderHook(() => useRecapAutoTrigger({ messageCount: 10, onRecap }));
    expect(onRecap).not.toHaveBeenCalled();
  });

  it('fires onRecap when awayMs ≥ 5min and messageCount ≥ 6', async () => {
    const { fireFocus } = installListenMock();
    const onRecap = vi.fn();
    renderHook(() => useRecapAutoTrigger({ messageCount: 10, onRecap }));
    await act(async () => {
      fireFocus({ awayMs: 5 * 60 * 1000 });
    });
    expect(onRecap).toHaveBeenCalledTimes(1);
  });

  it('does NOT fire when awayMs < 5min', async () => {
    const { fireFocus } = installListenMock();
    const onRecap = vi.fn();
    renderHook(() => useRecapAutoTrigger({ messageCount: 10, onRecap }));
    await act(async () => {
      fireFocus({ awayMs: 2 * 60 * 1000 });
    });
    expect(onRecap).not.toHaveBeenCalled();
  });

  it('does NOT fire when messageCount < 6', async () => {
    const { fireFocus } = installListenMock();
    const onRecap = vi.fn();
    renderHook(() => useRecapAutoTrigger({ messageCount: 3, onRecap }));
    await act(async () => {
      fireFocus({ awayMs: 10 * 60 * 1000 });
    });
    expect(onRecap).not.toHaveBeenCalled();
  });

  it('calls unlisten on unmount', async () => {
    const { unlistenFn } = installListenMock();
    const { unmount } = renderHook(() =>
      useRecapAutoTrigger({ messageCount: 10, onRecap: vi.fn() }),
    );
    expect(unlistenFn).not.toHaveBeenCalled();
    unmount();
    expect(unlistenFn).toHaveBeenCalled();
  });
});
