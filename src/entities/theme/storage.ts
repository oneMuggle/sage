/**
 * Theme 持久化 — 双写（localStorage 同步 + 后端异步）
 */
import { settingsClient } from '../../shared/api/settingsClient';

const CACHE_KEY = 'sage-theme';
const PRESET_KEY = 'sage-theme-preset';

export type ThemeMode = 'light' | 'dark' | 'system';

export async function loadTheme(): Promise<ThemeMode | null> {
  const remote = await settingsClient.getPreference<ThemeMode>('theme_mode');
  if (remote) {
    try {
      localStorage.setItem(CACHE_KEY, remote);
    } catch {
      // 隐私模式等
    }
    return remote;
  }
  try {
    return (localStorage.getItem(CACHE_KEY) as ThemeMode | null) ?? null;
  } catch {
    return null;
  }
}

export async function saveTheme(mode: ThemeMode): Promise<void> {
  try {
    localStorage.setItem(CACHE_KEY, mode);
  } catch {
    // 静默
  }
  await settingsClient.setPreference('theme_mode', mode, 'ui');
}

/** 加载主题预设 ID */
export async function loadThemePreset(): Promise<string | null> {
  const remote = await settingsClient.getPreference<string>('theme_preset');
  if (remote) {
    try {
      localStorage.setItem(PRESET_KEY, remote);
    } catch {
      // 隐私模式等
    }
    return remote;
  }
  try {
    return localStorage.getItem(PRESET_KEY);
  } catch {
    return null;
  }
}

/** 保存主题预设 ID */
export async function saveThemePreset(presetId: string): Promise<void> {
  try {
    localStorage.setItem(PRESET_KEY, presetId);
  } catch {
    // 静默
  }
  await settingsClient.setPreference('theme_preset', presetId, 'ui');
}
