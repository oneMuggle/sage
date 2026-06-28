/**
 * i18n — 自研国际化 Provider（API 与 main 100% 兼容 + win7 增强）
 *
 * 用法:
 *   <I18nProvider>
 *     <App />
 *   </I18nProvider>
 *
 *   const { t, locale, setLocale } = useI18n();
 *   <h1>{t('chat.title')}</h1>
 *
 * 架构:
 *   - locale 状态用 Zustand store（持久化到 localStorage）
 *   - t 函数在 Provider 内 useMemo 构造（依赖 locale）
 *   - 通过 Context 暴露 { locale, setLocale, t }
 *
 * 增强（超越 main）:
 *   - locale 自动持久化（main 无）
 *   - t() 支持 {placeholder}（main 无）
 *   - fallback 链 current → zh → key 字符串（main 只 current → key）
 */

import { createContext, useContext, useMemo, type ReactNode } from 'react';

import { en } from './en';
import { formatMessage } from './formatMessage';
import { useLocaleStore } from './useLocaleStore';
import { zh, type TranslationKey, type Locale } from './zh';

// 统一 re-export 类型
export type { Locale, TranslationKey } from './zh';

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  /** 翻译函数：fallback 链 current → zh → key 字符串；支持 {placeholder}。 */
  t: (key: TranslationKey, params?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

interface I18nProviderProps {
  children: ReactNode;
}

export function I18nProvider({ children }: I18nProviderProps) {
  // 精细订阅：只选 locale 和 setLocale，避免 store 其他字段变化触发重渲染
  const locale = useLocaleStore((s) => s.locale);
  const setLocale = useLocaleStore((s) => s.setLocale);

  const value = useMemo<I18nContextValue>(() => {
    const translations: Record<Locale, Record<string, string>> = { zh, en };
    const t: I18nContextValue['t'] = (key, params) => {
      const direct = translations[locale][key];
      const fallback = direct ?? translations.zh[key] ?? key;
      return params ? formatMessage(fallback, params) : fallback;
    };
    return { locale, setLocale, t };
  }, [locale, setLocale]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error('useI18n must be used within an <I18nProvider>');
  }
  return ctx;
}
