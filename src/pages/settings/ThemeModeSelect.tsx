/**
 * 主题模式三态开关 — 浅色 / 深色 / 跟随系统
 *
 * 只负责 mode（亮暗解析策略）; 主题配色由 ThemeSelector 的预设/CSS 主题决定。
 * 持久化与系统主题监听都在 ThemeProvider / entities/theme/storage 中完成。
 */

import clsx from 'clsx';

import { useTheme, type ThemeMode } from '../../app/providers/useTheme';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

import { SettingRow } from './components';

interface ModeOption {
  value: ThemeMode;
  labelKey: TranslationKey;
  testId: string;
}

const MODE_OPTIONS: ReadonlyArray<ModeOption> = [
  { value: 'light', labelKey: 'settings.theme.light', testId: 'theme-mode-light' },
  { value: 'dark', labelKey: 'settings.theme.dark', testId: 'theme-mode-dark' },
  { value: 'system', labelKey: 'settings.theme.system', testId: 'theme-mode-system' },
];

export function ThemeModeSelect() {
  const { mode, resolved, setMode } = useTheme();
  const { t } = useI18n();

  const desc =
    mode === 'system'
      ? t('settings.theme.mode_desc_system').replace(
          '{resolved}',
          resolved === 'dark' ? t('settings.theme.dark') : t('settings.theme.light'),
        )
      : t('settings.theme.mode_desc');

  return (
    <SettingRow label={t('settings.theme.mode_label')} desc={desc}>
      <div
        role="radiogroup"
        aria-label={t('settings.theme.mode_label')}
        className="flex items-center gap-1.5"
      >
        {MODE_OPTIONS.map((option) => {
          const checked = mode === option.value;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={checked}
              data-testid={option.testId}
              onClick={() => setMode(option.value)}
              className={clsx(
                'px-3 py-1 text-xs rounded border transition-colors',
                checked
                  ? 'bg-primary/10 text-primary border-primary'
                  : 'border-border text-text-secondary hover:border-border-hover',
              )}
            >
              {t(option.labelKey)}
            </button>
          );
        })}
      </div>
    </SettingRow>
  );
}
