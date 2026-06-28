import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';

import { getActiveTheme, saveActiveTheme } from '../../shared/api-client/themeCssClient';
import { useI18n } from '../../shared/lib/i18n';
import { validateCss } from '../../shared/lib/theme/cssValidator';
import type { ActiveTheme } from '../../shared/types/theme';

import { clearVars, injectFromCss } from './backgroundInjector';

const STORAGE_KEY = 'sage.theme.active';
const DEFAULT_ACTIVE: ActiveTheme = { presetId: 'light' };

interface ThemeContextValue {
  active: ActiveTheme;
  setPreset: (presetId: string) => Promise<void>;
  applyCustomCss: (css: string) => Promise<void>;
  reset: () => Promise<void>;
  isLoading: boolean;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used inside <ThemeProvider>');
  return ctx;
}

function readFromStorage(): ActiveTheme {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_ACTIVE;
    const parsed = JSON.parse(raw) as ActiveTheme;
    if (typeof parsed.presetId === 'string') return parsed;
  } catch (e) {
    console.warn('[ThemeProvider] localStorage corrupted', e);
  }
  return DEFAULT_ACTIVE;
}

function writeToStorage(active: ActiveTheme): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(active));
  } catch (e) {
    console.warn('[ThemeProvider] localStorage write failed', e);
  }
}

export function ThemeProvider({ children }: { children: ReactNode }): JSX.Element {
  const { t } = useI18n();
  const [active, setActive] = useState<ActiveTheme>(() => readFromStorage());

  useEffect(() => {
    if (active.customCss) injectFromCss(active.customCss);
    else clearVars();
  }, [active.presetId, active.customCss]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const result = await getActiveTheme();
      if (cancelled) return;
      if (result.success) {
        const backend = result.data;
        if (backend.presetId !== active.presetId || backend.customCss !== active.customCss) {
          setActive(backend);
          writeToStorage(backend);
        }
      } else {
        console.warn('[ThemeProvider] IPC backfill failed:', result.error);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setPreset = useCallback(
    async (presetId: string) => {
      const next: ActiveTheme = { presetId };
      setActive(next);
      writeToStorage(next);
      const result = await saveActiveTheme(next);
      if (!result.success) {
        console.warn(
          `[ThemeProvider] ${t('theme.editor.sync_failed') || 'sync failed'}:`,
          result.error,
        );
      }
    },
    [t],
  );

  const applyCustomCss = useCallback(
    async (css: string) => {
      const validation = validateCss(css);
      if (!validation.valid) {
        console.warn('[ThemeProvider] CSS invalid:', validation.errors);
        return;
      }
      const previous = active;
      const next: ActiveTheme = { presetId: previous.presetId, customCss: css };
      setActive(next);
      writeToStorage(next);
      const result = await saveActiveTheme(next);
      if (!result.success) {
        setActive(previous);
        writeToStorage(previous);
        console.warn(
          `[ThemeProvider] ${t('theme.editor.save_failed') || 'save failed'}:`,
          result.error,
        );
      }
    },
    [active, t],
  );

  const reset = useCallback(async () => {
    const next: ActiveTheme = { presetId: 'light' };
    setActive(next);
    writeToStorage(next);
    const result = await saveActiveTheme(next);
    if (!result.success) {
      console.warn('[ThemeProvider] reset IPC failed:', result.error);
    }
  }, []);

  const value: ThemeContextValue = { active, setPreset, applyCustomCss, reset, isLoading: false };
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
