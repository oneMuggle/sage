/**
 * i18n — 轻量国际化系统
 *
 * 用法:
 *   const { t, locale, setLocale } = useI18n();
 *   <h1>{t('chat.title')}</h1>
 */

import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';

import { en } from './en';
import { zh, type TranslationKey } from './zh';

export type Locale = 'zh' | 'en';

const translations: Record<Locale, Record<TranslationKey, string>> = { zh, en };

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: TranslationKey) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

interface I18nProviderProps {
  children: ReactNode;
  defaultLocale?: Locale;
}

// U10 (批次 C): locale 持久化 —— localStorage 优先于默认值
const LOCALE_STORAGE_KEY = 'sage.locale';

function loadStoredLocale(defaultLocale: Locale): Locale {
  try {
    const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    if (stored === 'zh' || stored === 'en') return stored;
  } catch {
    /* localStorage 不可用 (隐私模式等) → 默认 */
  }
  return defaultLocale;
}

export function I18nProvider({ children, defaultLocale = 'zh' }: I18nProviderProps) {
  const [locale, setLocaleState] = useState<Locale>(() => loadStoredLocale(defaultLocale));

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    try {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, next);
    } catch {
      /* 忽略持久化失败 */
    }
  }, []);

  const t = useCallback(
    (key: TranslationKey): string => {
      return translations[locale][key] ?? key;
    },
    [locale],
  );

  return <I18nContext.Provider value={{ locale, setLocale, t }}>{children}</I18nContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error('useI18n must be used within an <I18nProvider>');
  }
  return ctx;
}

export type { TranslationKey } from './zh';
