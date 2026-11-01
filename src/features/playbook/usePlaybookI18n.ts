/**
 * 项目规程 i18n 辅助（2026-11-01）。
 *
 * 有 I18nProvider 时跟随全局语言；无 Provider（如组件单测）回退中文词典，
 * 保证既有测试无需包裹 Provider。
 */
import { useCallback } from 'react';

import { useOptionalI18n } from '../../shared/lib/i18n';
import { zhPlaybook, type PlaybookTranslationKey } from '../../shared/lib/i18n/locales/zh/playbook';

export type PlaybookTParams = Record<string, string | number>;

export interface PlaybookI18n {
  t: (key: PlaybookTranslationKey) => string;
  tf: (key: PlaybookTranslationKey, params?: PlaybookTParams) => string;
}

export function usePlaybookI18n(): PlaybookI18n {
  const i18n = useOptionalI18n();
  const t = useCallback(
    (key: PlaybookTranslationKey): string => (i18n ? i18n.t(key) : zhPlaybook[key]),
    [i18n],
  );
  const tf = useCallback(
    (key: PlaybookTranslationKey, params: PlaybookTParams = {}): string =>
      t(key).replace(/\{(\w+)\}/g, (match, name: string) =>
        name in params ? String(params[name]) : match,
      ),
    [t],
  );
  return { t, tf };
}
