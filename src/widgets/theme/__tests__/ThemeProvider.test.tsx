import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/api-client/themeCssClient', () => ({
  getActiveTheme: vi.fn(),
  saveActiveTheme: vi.fn(),
}));
vi.mock('../../../shared/lib/theme/cssValidator', () => ({
  validateCss: vi.fn(() => ({ valid: true })),
}));
vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (k: string) => k, locale: 'en', setLocale: vi.fn() }),
}));
vi.mock('../backgroundInjector', () => ({
  injectFromCss: vi.fn(() => ({})),
  clearVars: vi.fn(),
  injectVars: vi.fn(),
}));

import * as client from '../../../shared/api-client/themeCssClient';
import { ThemeProvider, useTheme } from '../ThemeProvider';

const STORAGE_KEY = 'sage.theme.active';

describe('ThemeProvider - 启动序列', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });
  afterEach(() => localStorage.clear());

  it('uses default light preset when localStorage empty', async () => {
    vi.mocked(client.getActiveTheme).mockResolvedValue({
      success: true,
      data: { presetId: 'light' },
    });
    const { result } = renderHook(() => useTheme(), { wrapper: ThemeProvider });
    expect(result.current.active.presetId).toBe('light');
  });

  it('loads from localStorage synchronously on init', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ presetId: 'dark' }));
    vi.mocked(client.getActiveTheme).mockResolvedValue({
      success: true,
      data: { presetId: 'light' },
    });
    const { result } = renderHook(() => useTheme(), { wrapper: ThemeProvider });
    expect(result.current.active.presetId).toBe('dark');
  });

  it('async IPC backfill overrides localStorage if backend differs', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ presetId: 'dark' }));
    vi.mocked(client.getActiveTheme).mockResolvedValue({
      success: true,
      data: { presetId: 'ocean' },
    });
    const { result } = renderHook(() => useTheme(), { wrapper: ThemeProvider });
    await waitFor(() => {
      expect(result.current.active.presetId).toBe('ocean');
    });
  });

  it('keeps localStorage on IPC failure (no throw)', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ presetId: 'forest' }));
    vi.mocked(client.getActiveTheme).mockResolvedValue({ success: false, error: 'IPC down' });
    const { result } = renderHook(() => useTheme(), { wrapper: ThemeProvider });
    await waitFor(() => {
      expect(result.current.active.presetId).toBe('forest');
    });
  });
});

describe('ThemeProvider - setPreset', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });

  it('updates state + localStorage + calls saveActiveTheme', async () => {
    vi.mocked(client.getActiveTheme).mockResolvedValue({
      success: true,
      data: { presetId: 'light' },
    });
    vi.mocked(client.saveActiveTheme).mockResolvedValue({
      success: true,
      data: { presetId: 'ocean' },
    });
    const { result } = renderHook(() => useTheme(), { wrapper: ThemeProvider });
    await act(async () => {
      await result.current.setPreset('ocean');
    });
    expect(result.current.active.presetId).toBe('ocean');
  });

  it('keeps UI state on save failure', async () => {
    vi.mocked(client.getActiveTheme).mockResolvedValue({
      success: true,
      data: { presetId: 'light' },
    });
    vi.mocked(client.saveActiveTheme).mockResolvedValue({ success: false, error: '500' });
    const { result } = renderHook(() => useTheme(), { wrapper: ThemeProvider });
    await act(async () => {
      await result.current.setPreset('dark');
    });
    expect(result.current.active.presetId).toBe('dark');
  });
});

describe('ThemeProvider - applyCustomCss rollback', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });

  it('rolls back state when save fails', async () => {
    vi.mocked(client.getActiveTheme).mockResolvedValue({
      success: true,
      data: { presetId: 'ocean' },
    });
    vi.mocked(client.saveActiveTheme).mockResolvedValue({ success: false, error: '500' });
    const { result } = renderHook(() => useTheme(), { wrapper: ThemeProvider });
    // Wait for IPC backfill to complete (presetId -> 'ocean') before invoking applyCustomCss,
    // so the captured `previous` in the callback reflects the backfilled state.
    await waitFor(() => {
      expect(result.current.active.presetId).toBe('ocean');
    });
    await act(async () => {
      await result.current.applyCustomCss(':root { --color-bg: #f00; }');
    });
    expect(result.current.active.presetId).toBe('ocean');
    expect(result.current.active.customCss).toBeUndefined();
  });
});
