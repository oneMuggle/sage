import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

const mockLoad = vi.fn();
const mockSave = vi.fn();
const mockReset = vi.fn();
vi.mock('../../../entities/setting/storage', () => ({
  loadSettings: (...args: unknown[]) => mockLoad(...args),
  saveSettings: (...args: unknown[]) => mockSave(...args),
  resetSettings: (...args: unknown[]) => mockReset(...args),
}));

import { useSettings } from '../useSettings';
import { DEFAULT_SETTINGS } from '../../../entities/setting/types';

describe('useSettings (async)', () => {
  beforeEach(() => {
    localStorage.clear();
    mockLoad.mockReset();
    mockSave.mockReset();
    mockReset.mockReset();
  });

  it('初始时 isLoading=true，settings 是 DEFAULT_SETTINGS', async () => {
    mockLoad.mockResolvedValue(DEFAULT_SETTINGS);
    const { result } = renderHook(() => useSettings());
    expect(result.current.isLoading).toBe(true);
    expect(result.current.settings).toEqual(DEFAULT_SETTINGS);
  });

  it('loadSettings 完成后 isLoading=false，settings 是 loaded 值', async () => {
    mockLoad.mockResolvedValue({ ...DEFAULT_SETTINGS, maxContext: 8000 });
    const { result } = renderHook(() => useSettings());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.settings.maxContext).toBe(8000);
  });

  it('updateSettings 合并 partial 并 setSettings + persist', async () => {
    mockLoad.mockResolvedValue(DEFAULT_SETTINGS);
    mockSave.mockResolvedValue(undefined);
    const { result } = renderHook(() => useSettings());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.updateSettings({ maxContext: 16000 });
    });

    expect(result.current.settings.maxContext).toBe(16000);
    expect(mockSave).toHaveBeenCalledWith({ maxContext: 16000 });
  });

  it('resetSettings 还原为默认值', async () => {
    mockLoad.mockResolvedValue({ ...DEFAULT_SETTINGS, maxContext: 9999 });
    mockReset.mockResolvedValue(undefined);
    const { result } = renderHook(() => useSettings());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.resetSettings();
    });

    expect(result.current.settings).toEqual(DEFAULT_SETTINGS);
    expect(mockReset).toHaveBeenCalled();
  });
});
