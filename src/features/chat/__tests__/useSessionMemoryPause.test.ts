import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/lib/i18n', () => ({ useI18n: () => ({ locale: 'en' }) }));
vi.mock('sonner', () => ({ toast: { warning: vi.fn() } }));
import { useSessionMemoryPause } from '../useSessionMemoryPause';
const KEY = 'sage:paused-memory-sessions:v1';
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});
describe('durable device-local memory pause', () => {
  it('migrates legacy flags and survives a fresh component/app session', async () => {
    sessionStorage.setItem('sage:temp-chat-sessions', JSON.stringify(['session-a']));
    const first = renderHook(() => useSessionMemoryPause('session-a'));
    expect(first.result.current[0].has('session-a')).toBe(true);
    await waitFor(() => expect(JSON.parse(localStorage.getItem(KEY)!)).toContain('session-a'));
    first.unmount();
    sessionStorage.clear();
    const second = renderHook(() => useSessionMemoryPause('session-a'));
    expect(second.result.current[0].has('session-a')).toBe(true);
  });
  it('does not re-enable old legacy flags after a deliberate resume', async () => {
    localStorage.setItem(KEY, JSON.stringify(['session-a']));
    const first = renderHook(() => useSessionMemoryPause('session-a'));
    act(() => first.result.current[1](new Set()));
    await waitFor(() => expect(localStorage.getItem(KEY)).toBe('[]'));
    first.unmount();
    sessionStorage.setItem('sage:temp-chat-sessions', JSON.stringify(['session-a']));
    const second = renderHook(() => useSessionMemoryPause('session-a'));
    expect(second.result.current[0].has('session-a')).toBe(false);
  });
  it('fails closed for the active session when preferences cannot be decoded', () => {
    localStorage.setItem(KEY, '{corrupt');
    const state = renderHook(() => useSessionMemoryPause('session-a'));
    expect(state.result.current[0].has('session-a')).toBe(true);
    expect(state.result.current[2]).toBe(true);
    expect(localStorage.getItem(KEY)).toBe('{corrupt');
  });
});
