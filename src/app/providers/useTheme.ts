import { createContext, useContext } from 'react';

import type { ThemeCssPayload } from '../../features/theme/themeCssTypes';

export type ThemeMode = 'light' | 'dark' | 'system';

export type ActiveThemeSource = { kind: 'preset'; id: string } | { kind: 'css'; id: string };

interface ThemeContextValue {
  mode: ThemeMode;
  resolved: 'light' | 'dark';
  setMode: (mode: ThemeMode) => void;
  /** 当前主题预设 ID */
  presetId: string;
  /** 切换主题预设 */
  setPresetId: (id: string) => void;
  /** CSS 自定义主题列表（启动时加载） */
  cssThemes: ThemeCssPayload[];
  /** 当前激活主题来源 */
  activeSource: ActiveThemeSource;
  /** 切换到 CSS 自定义主题 */
  setActiveCssTheme: (id: string) => void;
  /** 刷新 CSS 主题列表（新建/删除后调用） */
  refreshCssThemes: () => Promise<void>;
}

export const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error('useTheme must be used within a <ThemeProvider>');
  }
  return ctx;
}
