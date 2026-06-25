import { useCallback, useEffect, useState, type ReactNode } from 'react';

import { getThemeById, DEFAULT_THEME_ID, type ThemeColors } from '../../entities/theme/presets';
import { loadTheme, loadThemePreset, saveTheme, saveThemePreset } from '../../entities/theme/storage';

import { ThemeContext, type ThemeMode } from './useTheme';

const VALID_MODES: ReadonlyArray<ThemeMode> = ['light', 'dark', 'system'];

function resolveSystemTheme(): 'light' | 'dark' {
  if (typeof window === 'undefined') return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

/** 将 camelCase 键转为 CSS 变量名: primaryHover → --color-primary-hover */
function camelToCssVar(key: string): string {
  return '--color-' + key.replace(/([A-Z])/g, '-$1').toLowerCase();
}

/** hex (#rrggbb) → "R G B" (空格分隔, 用于 rgba()) */
function hexToRgbTuple(hex: string): string {
  const clean = hex.replace('#', '');
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  return `${r} ${g} ${b}`;
}

/** 应用主题预设颜色到 CSS 自定义属性 */
function applyThemeColors(colors: ThemeColors): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement.style;

  for (const [key, value] of Object.entries(colors)) {
    const cssVar = camelToCssVar(key);
    root.setProperty(cssVar, value);
    // 非 overlay 颜色同时设置 -rgb 变体
    if (!value.startsWith('rgba')) {
      root.setProperty(`${cssVar}-rgb`, hexToRgbTuple(value));
    }
  }
}

/** 重置主题颜色（回退到 CSS 中定义的默认值） */
function resetThemeColors(): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement.style;
  // 移除所有 --color-* 内联样式, 让 CSS 中的 :root / [data-theme='dark'] 生效
  const toRemove: string[] = [];
  for (let i = 0; i < root.length; i++) {
    const prop = root[i];
    if (prop.startsWith('--color-')) {
      toRemove.push(prop);
    }
  }
  toRemove.forEach((p) => root.removeProperty(p));
}

/** 应用主题预设 + 亮/暗模式 */
function applyTheme(resolved: 'light' | 'dark', presetId: string): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.classList.toggle('dark', resolved === 'dark');

  const preset = getThemeById(presetId);
  if (preset && presetId !== DEFAULT_THEME_ID) {
    const colors = resolved === 'dark' ? preset.darkColors : preset.colors;
    applyThemeColors(colors);
  } else {
    resetThemeColors();
  }
}

interface ThemeProviderProps {
  children: ReactNode;
  defaultMode?: ThemeMode;
}

export function ThemeProvider({ children, defaultMode = 'system' }: ThemeProviderProps) {
  const [mode, setModeState] = useState<ThemeMode>(defaultMode);
  const [systemTheme, setSystemTheme] = useState<'light' | 'dark'>(() => resolveSystemTheme());
  const [presetId, setPresetIdState] = useState(DEFAULT_THEME_ID);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e: MediaQueryListEvent) => {
      setSystemTheme(e.matches ? 'dark' : 'light');
    };
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  useEffect(() => {
    loadTheme().then((m) => {
      if (m && VALID_MODES.includes(m)) {
        setModeState(m);
      }
    });
    loadThemePreset().then((id) => {
      if (id && getThemeById(id)) {
        setPresetIdState(id);
      }
    });
  }, []);

  const resolved: 'light' | 'dark' = mode === 'system' ? systemTheme : mode;

  useEffect(() => {
    applyTheme(resolved, presetId);
  }, [resolved, presetId]);

  const setMode = useCallback(
    (next: ThemeMode): void => {
      setModeState(next);
      void saveTheme(next);
    },
    [],
  );

  const setPresetId = useCallback(
    (id: string): void => {
      if (!getThemeById(id)) return;
      setPresetIdState(id);
      void saveThemePreset(id);
    },
    [],
  );

  return (
    <ThemeContext.Provider value={{ mode, resolved, setMode, presetId, setPresetId }}>
      {children}
    </ThemeContext.Provider>
  );
}
