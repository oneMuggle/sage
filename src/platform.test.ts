// src/platform.test.ts
import { describe, it, expect, vi, afterEach } from 'vitest';

describe('platform', () => {
  afterEach(() => {
    vi.resetModules();
    delete (window as any).electronAPI;
    localStorage.clear();
  });

  it('detects non-electron environment', async () => {
    delete (window as any).electronAPI;
    const { platform } = await import('./platform');
    expect(platform.isElectron()).toBe(false);
  });

  it('detects electron environment', async () => {
    (window as any).electronAPI = { invoke: vi.fn(), on: vi.fn(), off: vi.fn() };
    vi.resetModules();
    const { platform } = await import('./platform');
    expect(platform.isElectron()).toBe(true);
  });

  it('reads token from URL and stores in localStorage', async () => {
    delete (window as any).electronAPI;
    window.history.pushState({}, '', '/?token=test-123');
    vi.resetModules();
    await import('./platform');
    expect(localStorage.getItem('sage_auth_token')).toBe('test-123');
  });

  it('clears token from URL after reading', async () => {
    delete (window as any).electronAPI;
    window.history.pushState({}, '', '/?token=test-123');
    vi.resetModules();
    await import('./platform');
    expect(window.location.search).toBe('');
  });

  it('returns auth headers with bearer token', async () => {
    delete (window as any).electronAPI;
    localStorage.setItem('sage_auth_token', 'stored-token');
    vi.resetModules();
    const { platform } = await import('./platform');
    const headers = platform.getAuthHeaders();
    expect(headers).toEqual({ Authorization: 'Bearer stored-token' });
  });
});
