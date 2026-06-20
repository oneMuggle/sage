import { useEffect, useState, type ReactNode } from 'react';

import { ThemeContext, type ThemeMode } from './useTheme';

const STORAGE_KEY = 'sage-theme';
const VALID_MODES: ReadonlyArray<ThemeMode> = ['light', 'dark', 'system'];

function readStoredMode(): ThemeMode | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw && (VALID_MODES as ReadonlyArray<string>).includes(raw)) {
      return raw as ThemeMode;
    }
  } catch {
    // localStorage 不可用（隐私模式）— 返回 null 走 defaultMode
  }
  return null;
}

function resolveSystemTheme(): 'light' | 'dark' {
  if (typeof window === 'undefined') return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyTheme(resolved: 'light' | 'dark'): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.classList.toggle('dark', resolved === 'dark');
}

interface ThemeProviderProps {
  children: ReactNode;
  defaultMode?: ThemeMode;
}

/**
 * 主题 Provider。支持 light / dark / system 三种模式。
 * 写入 `localStorage`，并通过 `document.documentElement.classList` 切换 `dark` class
 * 配合 Tailwind 的 `dark:` 变体使用。
 */
export function ThemeProvider({ children, defaultMode = 'system' }: ThemeProviderProps) {
  const [mode, setModeState] = useState<ThemeMode>(() => readStoredMode() ?? defaultMode);
  const [systemTheme, setSystemTheme] = useState<'light' | 'dark'>(() => resolveSystemTheme());

  // 监听系统主题变化（仅在 mode === 'system' 时影响显示）
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e: MediaQueryListEvent) => {
      setSystemTheme(e.matches ? 'dark' : 'light');
    };
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  const resolved: 'light' | 'dark' = mode === 'system' ? systemTheme : mode;

  // 把 resolved 写回 <html class="dark">
  useEffect(() => {
    applyTheme(resolved);
  }, [resolved]);

  const setMode = (next: ThemeMode): void => {
    setModeState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // 静默失败 — 主题偏好非关键
    }
  };

  return (
    <ThemeContext.Provider value={{ mode, resolved, setMode }}>{children}</ThemeContext.Provider>
  );
}
