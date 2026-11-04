import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { read } = vi.hoisted(() => ({ read: vi.fn() }));
vi.mock('../../../../shared/api/settingsClient', () => ({
  settingsClient: { getPreferenceStrict: read, setPreferenceStrict: vi.fn() },
}));

import { displayModeStore } from '../displayModeStore';
import { __resetGlobalDisplayModeForTests } from '../globalDisplayModePreference';
import { useDisplayMode } from '../useDisplayMode';

function settingChanged(key: string): CustomEvent<{ key: string }> {
  return new CustomEvent('sage:setting-changed', { detail: { key } });
}

describe('useDisplayMode', () => {
  beforeEach(() => {
    read.mockReset();
    read.mockResolvedValue('trace');
    __resetGlobalDisplayModeForTests();
    displayModeStore.clearAll();
    sessionStorage.clear();
  });

  it('re-renders a mounted consumer after setSessionMode and setMessageMode', async () => {
    read.mockResolvedValue('detail');
    const { result } = renderHook(() => useDisplayMode('session-1', 'msg-1'));

    await waitFor(() => expect(result.current.mode).toBe('detail'));

    act(() => result.current.setSessionMode('trace'));
    expect(result.current.mode).toBe('trace');

    act(() => result.current.setMessageMode('result'));
    expect(result.current.mode).toBe('result');
  });

  it('lets a message override beat a session override and falls back on clear', async () => {
    read.mockResolvedValue('result');
    const { result } = renderHook(() => useDisplayMode('session-1', 'msg-1'));

    await waitFor(() => expect(result.current.mode).toBe('result'));

    act(() => result.current.setSessionMode('detail'));
    expect(result.current.mode).toBe('detail');

    act(() => result.current.setMessageMode('trace'));
    expect(result.current.mode).toBe('trace');

    act(() => result.current.clearMessageMode());
    expect(result.current.mode).toBe('detail');
  });

  it('shares one global preference read across hook instances', async () => {
    read.mockResolvedValue('result');
    const first = renderHook(() => useDisplayMode('session-a', null));
    const second = renderHook(() => useDisplayMode('session-b', null));

    await waitFor(() => expect(first.result.current.mode).toBe('result'));
    await waitFor(() => expect(second.result.current.mode).toBe('result'));

    expect(read).toHaveBeenCalledTimes(1);
  });

  it('reloads once for chat_display_mode events and ignores events for other keys', async () => {
    const { result } = renderHook(() => useDisplayMode('session-1', null));
    await waitFor(() => expect(read).toHaveBeenCalledTimes(1));

    await act(async () => {
      window.dispatchEvent(settingChanged('other_key'));
    });
    expect(read).toHaveBeenCalledTimes(1);

    read.mockResolvedValue('result');
    await act(async () => {
      // A duplicated event while a reload is in flight must not add another read.
      window.dispatchEvent(settingChanged('chat_display_mode'));
      window.dispatchEvent(settingChanged('chat_display_mode'));
    });
    expect(read).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(result.current.mode).toBe('result'));
  });

  it('retries the shared global read on the next subscription after a transient IPC failure', async () => {
    // 冷启动时后端可能尚未就绪：首次读取被拒，之后恢复。
    read.mockRejectedValueOnce(new Error('backend not ready'));
    read.mockResolvedValue('result');
    const first = renderHook(() => useDisplayMode('session-1', null));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    // 失败时保持默认档位，且不把 loaded 置真（否则本会话永不重读）。
    expect(read).toHaveBeenCalledTimes(1);
    expect(first.result.current.mode).toBe('trace');

    // 新的消费者挂载（后续消息出现 / 页面重挂载）会触发第二次读取。
    const second = renderHook(() => useDisplayMode('session-2', null));
    await waitFor(() => expect(second.result.current.mode).toBe('result'));
    expect(read).toHaveBeenCalledTimes(2);
    expect(first.result.current.mode).toBe('result');
  });
});
