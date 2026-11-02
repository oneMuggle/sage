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
});
