import {
  CODE_FONT_OPTIONS,
  FONT_SIZE_MAX,
  FONT_SIZE_MIN,
  UI_FONT_OPTIONS,
  type FontFamilyId,
} from '../../entities/font/fontOptions';
import { useFontSettings } from '../../entities/font/useFontSettings';
import { useI18n } from '../../shared/lib/i18n';

import { SettingRow } from './components';

export function FontSettingsSection() {
  const { settings, updateSettings, resetSettings, error, loading } = useFontSettings();
  const { t } = useI18n();
  return (
    <div>
      {(['ui', 'code'] as const).map((kind) => {
        const isUi = kind === 'ui';
        const familyKey = isUi ? 'fontUi' : 'fontCode';
        const sizeKey = isUi ? 'fontSizeUi' : 'fontSizeCode';
        const options = isUi ? UI_FONT_OPTIONS : CODE_FONT_OPTIONS;
        const familyLabel = t(isUi ? 'settings.font.ui' : 'settings.font.code');
        const sizeLabel = t(isUi ? 'settings.font.sizeUi' : 'settings.font.sizeCode');
        const selected = options.find((option) => option.id === settings[familyKey]);
        return (
          <div key={kind}>
            <SettingRow label={familyLabel}>
              <select
                aria-label={familyLabel}
                value={settings[familyKey]}
                disabled={loading}
                style={{ fontFamily: selected?.stack }}
                className="w-48 max-w-full px-2 py-1 text-sm border border-border rounded-radius-sm bg-bg text-text"
                onChange={(event) =>
                  updateSettings({ [familyKey]: event.target.value as FontFamilyId })
                }
              >
                {options.map((option) => (
                  <option key={option.id} value={option.id} style={{ fontFamily: option.stack }}>
                    {t(`font.option.${option.id}`)}
                  </option>
                ))}
              </select>
            </SettingRow>
            <SettingRow label={sizeLabel}>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="range"
                  aria-label={sizeLabel}
                  min={FONT_SIZE_MIN}
                  max={FONT_SIZE_MAX}
                  step={1}
                  value={settings[sizeKey]}
                  disabled={loading}
                  className="w-28 accent-primary"
                  onChange={(event) => updateSettings({ [sizeKey]: Number(event.target.value) })}
                />
                <input
                  type="number"
                  aria-label={sizeLabel}
                  min={FONT_SIZE_MIN}
                  max={FONT_SIZE_MAX}
                  step={1}
                  value={settings[sizeKey]}
                  disabled={loading}
                  className="w-16 px-2 py-1 text-sm border border-border rounded-radius-sm bg-bg text-text"
                  onChange={(event) => {
                    if (event.target.value !== '')
                      updateSettings({ [sizeKey]: Number(event.target.value) });
                  }}
                />
                <span className="text-xs text-text-muted">px</span>
              </div>
            </SettingRow>
          </div>
        );
      })}
      <div className="my-3 rounded-radius-sm border border-border p-3 space-y-2">
        <p className="font-sans" style={{ fontSize: 'var(--font-size-ui)' }}>
          {t('settings.font.preview')}
        </p>
        <code className="block font-mono text-code">const greeting = "Hello, 世界";</code>
      </div>
      <p className="text-xs text-text-muted">{t('settings.font.fallback')}</p>
      {error && (
        <p role="alert" className="text-sm text-error mt-2">
          {t(error === 'save' ? 'settings.font.saveError' : 'settings.font.loadError')}
        </p>
      )}
      <button
        type="button"
        onClick={resetSettings}
        disabled={loading}
        className="mt-2 text-sm text-primary hover:underline disabled:opacity-50"
      >
        {t('settings.font.reset')}
      </button>
    </div>
  );
}
