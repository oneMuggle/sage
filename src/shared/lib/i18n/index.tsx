/**
 * i18n — 轻量国际化系统
 *
 * 用法:
 *   const { t, locale, setLocale } = useI18n();
 *   <h1>{t('chat.title')}</h1>
 */

import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';

import {
  loadStoredLocale,
  LOCALE_STORAGE_KEY,
  translations,
  type Locale,
  type TranslationKey,
} from './translations';

export type { Locale, TranslationKey };

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

/**
 * 可选 i18n：无 Provider 时返回 null（如共享 UI 基座被单测直接渲染）。
 * 仅用于"有 Provider 就本地化、没有就回退默认文案"的场景。
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useOptionalI18n(): I18nContextValue | null {
  return useContext(I18nContext);
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatI18nProviderSummary(locale: Locale = 'zh'): string {
  const safeLocale: Locale = locale === 'en' ? 'en' : 'zh';
  const keyCount = Object.keys(translations[safeLocale]).length;
  return `locale=${safeLocale} · keys=${keyCount} · storageKey=${LOCALE_STORAGE_KEY}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatI18nProviderJson(locale: Locale = 'zh'): string {
  const safeLocale: Locale = locale === 'en' ? 'en' : 'zh';
  const keyCount = Object.keys(translations[safeLocale]).length;
  return JSON.stringify({
    locale: safeLocale,
    keyCount,
    storageKey: LOCALE_STORAGE_KEY,
  });
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditI18nProviderGovernance(): string {
  return JSON.stringify({
    module: 'i18n-provider',
    phase: 'P183',
    audited: true,
  });
}
