/**
 * Markdown 渲染器本地 i18n hook。
 *
 * 设计取舍：
 * - 用 `useOptionalI18n()` 取 locale —— 无 provider 时返回 null 而不是抛错，
 *   让 Markdown 渲染器在单元测试、脱离 AppRoot 的宿主（如产物预览 standalone）
 *   也能安全运行（FileReferenceLinks.test.tsx 即不包 I18nProvider）。
 * - provider 存在时跟随全局 locale 切换；缺失时默认中文。
 * - 类型安全：`t(key)` 的 key 来自 `MarkdownI18nKey`，不存在 key 编译期报错。
 */

import { useCallback } from 'react';
import { useOptionalI18n } from '../../shared/lib/i18n';
import { MARKDOWN_I18N_DICTS, type MarkdownI18nKey } from './i18n';

/**
 * 返回一个 markdown 文案翻译函数。
 *
 * @example
 * const t = useMdI18n();
 * <button>{t('md.table.copy')}</button>
 */
export function useMdI18n(): (key: MarkdownI18nKey, params?: Record<string, string | number>) => string {
  const i18n = useOptionalI18n();
  const locale = i18n?.locale ?? 'zh';
  // 仅支持 zh/en，其它 locale 回退到 en
  const dict = MARKDOWN_I18N_DICTS[locale === 'en' ? 'en' : 'zh'];

  return useCallback(
    (key: MarkdownI18nKey, params?: Record<string, string | number>) => {
      const raw = dict[key] ?? key;
      if (!params) return raw;
      return Object.entries(params).reduce(
        (acc, [k, v]) => acc.replace(`{${k}}`, String(v)),
        raw,
      );
    },
    [dict],
  );
}
