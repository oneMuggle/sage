import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

import type { Locale } from './zh';

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
