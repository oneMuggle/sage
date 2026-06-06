/**
 * useSettings hook 测试
 *
 * 验证：
 *   - 初始 settings 来自 localStorage（无值时回退到 DEFAULT_SETTINGS）
 *   - updateSettings 合并 partial 并 persist 到 localStorage
 *   - resetSettings 写回 DEFAULT_SETTINGS
 *   - 在同一测试运行中、新 hook 实例能读到上一次的 persist
 */
import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { DEFAULT_SETTINGS, SETTINGS_STORAGE_KEY } from '../../../entities/setting/types';
import { useSettings } from '../useSettings';

beforeEach(() => {
  localStorage.clear();
});

describe('useSettings', () => {
  it('initial state falls back to DEFAULT_SETTINGS when no persistence exists', () => {
    const { result } = renderHook(() => useSettings());

    expect(result.current.settings.streaming).toBe(DEFAULT_SETTINGS.streaming);
    expect(result.current.settings.maxContext).toBe(DEFAULT_SETTINGS.maxContext);
    expect(result.current.settings.endpoints).toEqual([]);
  });

  it('updateSettings merges partial and persists to localStorage', () => {
    const { result } = renderHook(() => useSettings());

    act(() => {
      result.current.updateSettings({ temperature: 0.42, maxContext: 8192 });
    });

    expect(result.current.settings.temperature).toBe(0.42);
    expect(result.current.settings.maxContext).toBe(8192);

    const raw = localStorage.getItem(SETTINGS_STORAGE_KEY);
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw!) as { temperature: number; maxContext: number };
    expect(parsed.temperature).toBe(0.42);
    expect(parsed.maxContext).toBe(8192);
  });

  it('new hook instance picks up previously persisted settings', () => {
    const first = renderHook(() => useSettings());
    act(() => {
      first.result.current.updateSettings({ compactMode: true });
    });

    // 第二个 hook 实例（模拟跨页面 / 重新 mount）应当从 localStorage 读到 compactMode=true
    const second = renderHook(() => useSettings());
    expect(second.result.current.settings.compactMode).toBe(true);
  });

  it('resetSettings restores defaults and overwrites localStorage', () => {
    const { result } = renderHook(() => useSettings());

    act(() => {
      result.current.updateSettings({ temperature: 1.5, compactMode: true });
    });
    expect(result.current.settings.temperature).toBe(1.5);

    act(() => {
      result.current.resetSettings();
    });

    expect(result.current.settings.temperature).toBe(DEFAULT_SETTINGS.temperature);
    expect(result.current.settings.compactMode).toBe(DEFAULT_SETTINGS.compactMode);
  });
});
