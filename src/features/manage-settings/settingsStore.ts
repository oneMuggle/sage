/**
 * 2026-08-26: 全局 zustand store for application settings.
 *
 * 之前的 useSettings() 在每个组件里独立 useState, 导致 Sidebar 首次挂载时的
 * settings 与 Settings 页保存后的 settings 不是同一份引用 — Sidebar 永远
 * 显示首次 mount 时的 "未配置", 即使端点已保存.
 *
 * 修复方案: 把 settings 挪到全局 zustand store, 所有 useSettings() 调用订阅
 * 同一份 state. 一个组件 updateSettings 立刻触发所有订阅者重渲染, Sidebar
 * 状态自动跟着 Settings 页更新.
 *
 * - loadSettings 由调用方显式触发 (e.g. App.tsx 启动时调一次),
 *   避免每个组件挂载都重新拉.
 * - 测试用 useSettingsStore.setState(...) 重置.
 */
import { create } from 'zustand';

import {
  loadSettings as loadSettingsFromStorage,
  resetSettings as resetSettingsLib,
  saveSettings,
} from '../../entities/setting/storage';
import type { AppSettings } from '../../entities/setting/types';
import { DEFAULT_SETTINGS, withDemoSettingsDefaults } from '../../entities/setting/types';
import { getDemoModeOverride, setDemoModeOverride } from '../../shared/api/demoRuntime';

interface SettingsStoreState {
  settings: AppSettings;
  isLoading: boolean;

  loadSettings: () => Promise<void>;
  updateSettings: (partial: Partial<AppSettings>) => Promise<void>;
  resetSettings: () => Promise<void>;
}

export const useSettingsStore = create<SettingsStoreState>((set) => ({
  settings: { ...DEFAULT_SETTINGS },
  isLoading: true,

  loadSettings: async () => {
    set({ isLoading: true });
    try {
      let s = await loadSettingsFromStorage();
      // 演示模式 (2026-08-27): main 进程经 argv 注入演示标志时, 往内存注入
      // 演示端点 + 模型选择 (不回写存储), 让聊天页前置校验通过、编排流可触发.
      // 关闭演示模式重启即恢复真实配置.
      if (typeof window !== 'undefined' && window.electronAPI?.demoMode === true) {
        setDemoModeOverride(true);
        s = withDemoSettingsDefaults(s);
      } else if (typeof window !== 'undefined') {
        setDemoModeOverride(false);
      }
      set({ settings: s, isLoading: false });
    } catch {
      set({ isLoading: false });
    }
  },

  updateSettings: async (partial) => {
    set((state) => ({ settings: { ...state.settings, ...partial } }));
    await saveSettings(partial);
  },

  resetSettings: async () => {
    const wasDemoProcess = getDemoModeOverride() === true;
    if (typeof window !== 'undefined') {
      const result = await window.electronAPI?.resetDemoMode?.();
      if (result && result.ok === false) {
        setDemoModeOverride(true);
        throw new Error('无法清理演示模式设置');
      }
    }
    await resetSettingsLib();
    setDemoModeOverride(wasDemoProcess);
    set({ settings: { ...DEFAULT_SETTINGS } });
  },
}));
