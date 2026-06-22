import { useEffect, useState, type ReactNode } from 'react';

import { loadTheme, saveTheme } from '../../entities/theme/storage';
import { ThemeContext, type ThemeMode } from './useTheme';

const VALID_MODES: ReadonlyArray<ThemeMode> = ['light', 'dark', 'system'];

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

export function ThemeProvider({ children, defaultMode = 'system' }: ThemeProviderProps) {
  const [mode, setModeState] = useState<ThemeMode>(defaultMode);
  const [isLoading, setIsLoading] = useState(true);
  const [systemTheme, setSystemTheme] = useState<'light' | 'dark'>(() => resolveSystemTheme());

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
    loadTheme()
      .then((m) => {
        if (m && VALID_MODES.includes(m)) {
          setModeState(m);
        }
      })
      .finally(() => setIsLoading(false));
  }, []);

  const resolved: 'light' | 'dark' = mode === 'system' ? systemTheme : mode;

  useEffect(() => {
    applyTheme(resolved);
  }, [resolved]);

  const setMode = (next: ThemeMode): void => {
    setModeState(next);
    void saveTheme(next);
  };

  return (
    <ThemeContext.Provider value={{ mode, resolved, setMode, isLoading }}>
      {children}
    </ThemeContext.Provider>
  );
}
