/**
 * 2026-08-26: 共享 settings store 的 cross-instance 契约.
 *
 * Bug: useSettings 之前每个组件独立 useState, Sidebar 在首次挂载时 loadSettings,
 * Settings 页 updateSettings 只更新该组件 React state, Sidebar 永远不刷新 —
 * 导致 "已配置" 端点保存后 Sidebar 底部状态仍卡在 "未配置".
 *
 * 修复方案: 把 settings 挪到全局 zustand store, 所有 useSettings() 调用共享同一份
 * state. 一个组件 updateSettings 立刻触发所有订阅者重渲染.
 *
 * 测试覆盖:
 *   - 两个 useSettings 共享 settings 引用 (subscribe 后两边都收到更新)
 *   - updateSettings 一个组件触发, 另一个组件订阅立即收到新值
 *   - loadSettings 一个组件触发, 另一个组件的 isLoading 也会切到 false
 *   - resetSettings 一个组件触发, 另一个组件的 settings 也变 DEFAULT
 *   - setSettings bypass 也能传播 (边角场景: 直接 store.setState)
 */
import { act, renderHook } from '@testing-library/react';
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
  act(() => {
    useSettingsStore.setState({
      settings: { ...DEFAULT_SETTINGS },
      isLoading: true,
    });
  });
}

describe('useSettings shared store (2026-08-26)', () => {
  beforeEach(() => {
    localStorage.clear();
    mockLoad.mockReset();
    mockSave.mockReset();
    mockReset.mockReset();
    resetStore();
  });

  it('两个组件调用 useSettings() 看到的是同一份 settings 引用', () => {
    mockLoad.mockResolvedValue(DEFAULT_SETTINGS);
    const a = renderHook(() => useSettings());
    const b = renderHook(() => useSettings());
    expect(a.result.current.settings).toBe(b.result.current.settings);
  });

  it('A 组件 updateSettings → B 组件订阅立即收到新值 (核心修复)', async () => {
    mockLoad.mockResolvedValue(DEFAULT_SETTINGS);
    const a = renderHook(() => useSettings());
    const b = renderHook(() => useSettings());

    await act(async () => {
      await a.result.current.updateSettings({ maxContext: 16000 });
    });

    expect(a.result.current.settings.maxContext).toBe(16000);
    expect(b.result.current.settings.maxContext).toBe(16000);
  });

  it('A 组件 updateSettings 触发 endpoints[0].apiKey → B 组件也看到', async () => {
    mockLoad.mockResolvedValue(DEFAULT_SETTINGS);
    const a = renderHook(() => useSettings());
    const b = renderHook(() => useSettings());

    const newEp = {
      ...DEFAULT_SETTINGS.endpoints[0],
      id: 'ep1',
      name: 'LM Studio',
      baseUrl: 'http://127.0.0.1:1234/v1',
      apiKey: 'sk-NEW',
    };
    await act(async () => {
      await a.result.current.updateSettings({ endpoints: [newEp] });
    });

    expect(a.result.current.settings.endpoints[0].apiKey).toBe('sk-NEW');
    expect(b.result.current.settings.endpoints[0].apiKey).toBe('sk-NEW');
  });

  it('A 组件 loadSettings → B 组件 isLoading 也变 false, settings 同步', async () => {
    mockLoad.mockResolvedValue({ ...DEFAULT_SETTINGS, maxContext: 8000 });
    const a = renderHook(() => useSettings());
    const b = renderHook(() => useSettings());

    expect(a.result.current.isLoading).toBe(true);
    expect(b.result.current.isLoading).toBe(true);

    await act(async () => {
      await a.result.current.loadSettings();
    });

    expect(a.result.current.isLoading).toBe(false);
    expect(b.result.current.isLoading).toBe(false);
    expect(a.result.current.settings.maxContext).toBe(8000);
    expect(b.result.current.settings.maxContext).toBe(8000);
  });

  it('A 组件 resetSettings → B 组件 settings 同步为 DEFAULT_SETTINGS', async () => {
    mockLoad.mockResolvedValue({ ...DEFAULT_SETTINGS, maxContext: 9999 });
    mockReset.mockResolvedValue(undefined);
    const a = renderHook(() => useSettings());
    const b = renderHook(() => useSettings());

    await act(async () => {
      await a.result.current.resetSettings();
    });

    expect(a.result.current.settings).toEqual(DEFAULT_SETTINGS);
    expect(b.result.current.settings).toEqual(DEFAULT_SETTINGS);
  });

  it('updateSettings 同时调 saveSettings 持久化', async () => {
    mockLoad.mockResolvedValue(DEFAULT_SETTINGS);
    mockSave.mockResolvedValue(undefined);
    const { result } = renderHook(() => useSettings());

    await act(async () => {
      await result.current.updateSettings({ maxContext: 16000 });
    });

    expect(mockSave).toHaveBeenCalledWith({ maxContext: 16000 });
  });

  it('resetSettings 同时调 storage.resetSettings()', async () => {
    mockLoad.mockResolvedValue(DEFAULT_SETTINGS);
    mockReset.mockResolvedValue(undefined);
    const { result } = renderHook(() => useSettings());

    await act(async () => {
      await result.current.resetSettings();
    });

    expect(mockReset).toHaveBeenCalled();
  });

  it('loadSettings 失败时 isLoading 仍切到 false (避免 UI 永久 loading)', async () => {
    mockLoad.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useSettings());

    await act(async () => {
      await result.current.loadSettings();
    });

    expect(result.current.isLoading).toBe(false);
  });

  it('直接 store.setState 也能传播给所有 useSettings 订阅者', () => {
    mockLoad.mockResolvedValue(DEFAULT_SETTINGS);
    const a = renderHook(() => useSettings());
    const b = renderHook(() => useSettings());

    act(() => {
      useSettingsStore.setState({ settings: { ...DEFAULT_SETTINGS, maxContext: 7777 } });
    });

    expect(a.result.current.settings.maxContext).toBe(7777);
    expect(b.result.current.settings.maxContext).toBe(7777);
  });
});
