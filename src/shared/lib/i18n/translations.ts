/**
 * i18n 词典与 locale 工具 —— 纯 TS，不含 React。
 *
 * 2026-11-02: settingsStore 经 electron 主进程编译链
 * （desktopInvoke → demoFlag → settingsStore）引用本模块，
 * 而 tsconfig.electron.json 未开 --jsx，不能引用 .tsx 文件。
 * 故词典/类型/工具函数与 React Provider 拆开：React 部分留在 index.tsx。
 */

import { chatReadingEn, chatReadingZh } from './chatReading';
import { en } from './en';
import { zh, type TranslationKey as CoreTranslationKey } from './zh';

export type Locale = 'zh' | 'en';

/** 核心词典（zh.ts）+ 按功能拆出的词典模块（见 chatReading.ts 的说明） */
export type TranslationKey = CoreTranslationKey | keyof typeof chatReadingZh;

export const translations: Record<Locale, Record<TranslationKey, string>> = {
  zh: { ...zh, ...chatReadingZh },
  en: { ...en, ...chatReadingEn },
};

/** U10 (批次 C): locale 持久化 —— localStorage 优先于默认值 */
export const LOCALE_STORAGE_KEY = 'sage.locale';

export function loadStoredLocale(defaultLocale: Locale): Locale {
  try {
    const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    if (stored === 'zh' || stored === 'en') return stored;
  } catch {
    /* localStorage 不可用 (隐私模式等) → 默认 */
  }
  return defaultLocale;
}

/**
 * 静态翻译：供组件树之外（zustand store、事件处理器等）取当前 locale 文案。
 *
 * 2026-11-02: 设置保存失败 toast 在 settingsStore 中触发，拿不到 useI18n hook；
 * 复用 Provider 持久化到 localStorage 的 locale，未持久化时回退 zh。
 */
export function translateStatic(key: TranslationKey, fallbackLocale: Locale = 'zh'): string {
  const locale = loadStoredLocale(fallbackLocale);
  return translations[locale][key] ?? key;
}
