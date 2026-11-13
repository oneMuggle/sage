// src/hooks/usePlatform.test.ts
import { describe, it, expect, vi, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';

describe('usePlatform', () => {
  afterEach(() => {
    vi.resetModules();
    delete (window as any).electronAPI;
    localStorage.clear();
  });

  it('returns isElectron false in web mode', async () => {
    delete (window as any).electronAPI;
    vi.resetModules();
    const { usePlatform } = await import('./usePlatform');
    const { result } = renderHook(() => usePlatform());
    expect(result.current.isElectron).toBe(false);
  });

  it('returns auth headers', async () => {
    delete (window as any).electronAPI;
    localStorage.setItem('sage_auth_token', 'test-token');
    vi.resetModules();
    const { usePlatform } = await import('./usePlatform');
    const { result } = renderHook(() => usePlatform());
    expect(result.current.authHeaders).toEqual({ Authorization: 'Bearer test-token' });
  });

  it('returns invoke function', async () => {
    delete (window as any).electronAPI;
    vi.resetModules();
    const { usePlatform } = await import('./usePlatform');
    const { result } = renderHook(() => usePlatform());
    expect(typeof result.current.invoke).toBe('function');
  });
});
