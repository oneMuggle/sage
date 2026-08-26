import { renderHook, act } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockLoad = vi.fn();
const mockSave = vi.fn();
const mockReset = vi.fn();
vi.mock('../../../entities/setting/storage', () => ({
  loadSettings: (...args: unknown[]) => mockLoad(...args),
  saveSettings: (...args: unknown[]) => mockSave(...args),
  resetSettings: (...args: unknown[]) => mockReset(...args),
}));

import { DEFAULT_SETTINGS } from '../../../entities/setting/types';
import { useSettings } from '../useSettings';
import { useSettingsStore } from '../settingsStore';

function resetStore() {
  useSettingsStore.setState({
    settings: { ...DEFAULT_SETTINGS },
    isLoading: true,
  });
}

/**
 * 2026-08-26: useSettings 改为订阅全局 zustand store. 共享 state, 测试需要在
 * beforeEach 重置 store (跟 src/shared/lib/store.test 一致). loadSettings 不再
 * 在 mount 时自动触发, 由调用方显式触发 (AppStartupSettings / 测试代码).
 */
describe('useSettings (shared store)', () => {
  beforeEach(() => {
    localStorage.clear();
    mockLoad.mockReset();
    mockSave.mockReset();
    mockReset.mockReset();
    resetStore();
  });

  it('初始 state: isLoading=true, settings 是 DEFAULT_SETTINGS', () => {
    const { result } = renderHook(() => useSettings());
    expect(result.current.isLoading).toBe(true);
    expect(result.current.settings).toEqual(DEFAULT_SETTINGS);
  });

  it('显式调 loadSettings 后 isLoading=false, settings 是 loaded 值', async () => {
    mockLoad.mockResolvedValue({ ...DEFAULT_SETTINGS, maxContext: 8000 });
    const { result } = renderHook(() => useSettings());

    await act(async () => {
      await result.current.loadSettings();
    });

    expect(result.current.isLoading).toBe(false);
    expect(result.current.settings.maxContext).toBe(8000);
  });

  it('updateSettings 合并 partial 并 saveSettings 持久化', async () => {
    mockLoad.mockResolvedValue(DEFAULT_SETTINGS);
    mockSave.mockResolvedValue(undefined);
    const { result } = renderHook(() => useSettings());

    await act(async () => {
      await result.current.loadSettings();
    });

    await act(async () => {
      await result.current.updateSettings({ maxContext: 16000 });
    });

    expect(result.current.settings.maxContext).toBe(16000);
    expect(mockSave).toHaveBeenCalledWith({ maxContext: 16000 });
  });

  it('resetSettings 还原为 DEFAULT_SETTINGS', async () => {
    mockLoad.mockResolvedValue({ ...DEFAULT_SETTINGS, maxContext: 9999 });
    mockReset.mockResolvedValue(undefined);
    const { result } = renderHook(() => useSettings());

    await act(async () => {
      await result.current.loadSettings();
    });

    await act(async () => {
      await result.current.resetSettings();
    });

    expect(result.current.settings).toEqual(DEFAULT_SETTINGS);
    expect(mockReset).toHaveBeenCalled();
  });

  it('loadSettings 失败时 isLoading 仍变 false, settings 保留旧值', async () => {
    mockLoad.mockResolvedValue({ ...DEFAULT_SETTINGS, maxContext: 7777 });
    const { result } = renderHook(() => useSettings());
    await act(async () => {
      await result.current.loadSettings();
    });
    expect(result.current.settings.maxContext).toBe(7777);

    mockLoad.mockRejectedValueOnce(new Error('boom'));
    await act(async () => {
      await result.current.loadSettings();
    });

    expect(result.current.isLoading).toBe(false);
    // loadSettings 失败时 store 不覆盖现有 settings (避免丢失本地修改)
    expect(result.current.settings.maxContext).toBe(7777);
  });
});
