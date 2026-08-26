import type { AppSettings } from '../../entities/setting/types';

import { useSettingsStore } from './settingsStore';

export interface UseSettingsReturn {
  settings: AppSettings;
  isLoading: boolean;
  loadSettings: () => Promise<void>;
  updateSettings: (partial: Partial<AppSettings>) => Promise<void>;
  resetSettings: () => Promise<void>;
}

/**
 * React hook for application settings.
 *
 * 2026-08-26: 改为订阅全局 zustand store — 所有 useSettings() 调用共享同一份
 * state. 之前的 useState 写法导致每个组件有独立 state, Sidebar 永远不更新.
 *
 * 注意: loadSettings 不在 mount 时自动触发, 由 App.tsx 的 AppStartupSettings
 * 组件在 app 启动时调用一次. 这样 7 个调用方不会触发 7 次并发 load.
 */
export function useSettings(): UseSettingsReturn {
  const settings = useSettingsStore((s) => s.settings);
  const isLoading = useSettingsStore((s) => s.isLoading);
  const loadSettings = useSettingsStore((s) => s.loadSettings);
  const updateSettings = useSettingsStore((s) => s.updateSettings);
  const resetSettings = useSettingsStore((s) => s.resetSettings);

  return { settings, isLoading, loadSettings, updateSettings, resetSettings };
}
