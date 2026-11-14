// Wiki Settings Store - 项目级设置（任务路由 + 推理模式）
import { create } from 'zustand';

import { getWikiSettings, updateWikiSettings } from '../../shared/api-client/wiki';
import { DEFAULT_WIKI_SETTINGS } from '../../shared/types/wiki';
import type { WikiProjectSettings } from '../../shared/types/wiki';

interface WikiSettingsStoreState {
  settings: WikiProjectSettings;
  /** 最近一次成功加载/保存所属的项目路径，用于判断是否需要重新拉取。 */
  loadedProjectPath: string | null;
  isLoading: boolean;
  isSaving: boolean;
  error: string | null;

  loadSettings: (projectPath: string) => Promise<void>;
  saveSettings: (projectPath: string, next: WikiProjectSettings) => Promise<boolean>;
  reset: () => void;
}

function errorMessage(prefix: string, e: unknown): string {
  return `${prefix}: ${e instanceof Error ? e.message : String(e)}`;
}

export const useWikiSettingsStore = create<WikiSettingsStoreState>((set) => ({
  settings: DEFAULT_WIKI_SETTINGS,
  loadedProjectPath: null,
  isLoading: false,
  isSaving: false,
  error: null,

  loadSettings: async (projectPath) => {
    set({ isLoading: true, error: null });
    try {
      const settings = await getWikiSettings(projectPath);
      set({ settings, loadedProjectPath: projectPath, isLoading: false });
    } catch (e) {
      set({ error: errorMessage('加载 Wiki 设置失败', e), isLoading: false });
    }
  },

  saveSettings: async (projectPath, next) => {
    set({ isSaving: true, error: null });
    try {
      const saved = await updateWikiSettings(projectPath, next);
      set({ settings: saved, loadedProjectPath: projectPath, isSaving: false });
      return true;
    } catch (e) {
      set({ error: errorMessage('保存 Wiki 设置失败', e), isSaving: false });
      return false;
    }
  },

  reset: () =>
    set({
      settings: DEFAULT_WIKI_SETTINGS,
      loadedProjectPath: null,
      isLoading: false,
      isSaving: false,
      error: null,
    }),
}));
