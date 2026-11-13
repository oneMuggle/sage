import { renderHook } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';

describe('usePlatform', () => {
  afterEach(() => {
    vi.resetModules();
    delete window.electronAPI;
    localStorage.clear();
  });

  it('returns isElectron false in web mode', async () => {
    delete window.electronAPI;
    vi.resetModules();
    const { usePlatform } = await import('./usePlatform');
    const { result } = renderHook(() => usePlatform());
    expect(result.current.isElectron).toBe(false);
  });

  it('returns auth headers', async () => {
    delete window.electronAPI;
    localStorage.setItem('sage_auth_token', 'test-token');
    vi.resetModules();
    const { usePlatform } = await import('./usePlatform');
    const { result } = renderHook(() => usePlatform());
    expect(result.current.authHeaders).toEqual({ Authorization: 'Bearer test-token' });
  });

  it('returns invoke function', async () => {
    delete window.electronAPI;
    vi.resetModules();
    const { usePlatform } = await import('./usePlatform');
    const { result } = renderHook(() => usePlatform());
    expect(typeof result.current.invoke).toBe('function');
  });
});
