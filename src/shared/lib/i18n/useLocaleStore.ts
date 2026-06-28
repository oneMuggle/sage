import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

// Locale 类型临时本地定义；Task 4 创建 zh.ts 后会替换为从 './zh' 导入。
// 这里保持与 spec §4.1 一致：'zh' | 'en'。
type Locale = 'zh' | 'en';

interface LocaleState {
  locale: Locale;
  setLocale: (locale: Locale) => void;
}

export const useLocaleStore = create<LocaleState>()(
  persist(
    (set) => ({
      locale: 'zh',
      setLocale: (locale) => set({ locale }),
    }),
    {
      name: 'sage-locale', // localStorage key
      storage: createJSONStorage(() => localStorage),
      version: 1,
    },
  ),
);