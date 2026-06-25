/**
 * ThemeGallery — 主题画廊组件
 *
 * 网格展示 11 套主题（6 基础 + 5 装饰），点击切换主题。
 */
import { clsx } from 'clsx';
import { useTheme } from '../../app/providers/useTheme';
import { themePresets } from '../../entities/theme/presets';
import { decorativePresets } from '../../entities/theme/decorative-presets';
import { ThemeCover } from './ThemeCover';
import { useI18n } from '../../shared/lib/i18n';

export function ThemeGallery() {
  const { presetId, setPresetId } = useTheme();
  const { t } = useI18n();

  return (
    <div className="space-y-6">
      {/* 基础主题区域 */}
      <div>
        <h3 className="text-sm font-medium text-text-secondary mb-3">
          {t('theme.gallery.section_basic')}
        </h3>
        <div className="grid grid-cols-3 gap-3">
          {themePresets.map((preset) => {
            const isActive = presetId === preset.id;
            return (
              <button
                key={preset.id}
                onClick={() => setPresetId(preset.id)}
                className={clsx(
                  'group relative rounded-radius-md border-2 overflow-hidden transition-all',
                  'hover:shadow-md hover:scale-105',
                  isActive
                    ? 'border-primary ring-2 ring-primary/30 shadow-md'
                    : 'border-border hover:border-border-hover',
                )}
              >
                {/* 封面图 */}
                <div className="aspect-[3/2] bg-bg-subtle">
                  <ThemeCover
                    src="/themes/covers/basic.svg"
                    alt={preset.name}
                    gradientFrom={preset.colors.primary}
                    gradientTo={preset.colors.secondary}
                  />
                </div>

                {/* 主题信息 */}
                <div className="p-2 text-left">
                  <div
                    className={clsx(
                      'text-sm font-medium truncate',
                      isActive ? 'text-primary' : 'text-text',
                    )}
                  >
                    {preset.name}
                  </div>
                  <div className="text-xs text-text-muted truncate">{preset.description}</div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* 装饰主题区域 */}
      <div>
        <h3 className="text-sm font-medium text-text-secondary mb-3">
          {t('theme.gallery.section_decorative')}
        </h3>
        <div className="grid grid-cols-3 gap-3">
          {decorativePresets.map((preset) => {
            const isActive = presetId === preset.id;
            return (
              <button
                key={preset.id}
                onClick={() => setPresetId(preset.id)}
                className={clsx(
                  'group relative rounded-radius-md border-2 overflow-hidden transition-all',
                  'hover:shadow-md hover:scale-105',
                  isActive
                    ? 'border-primary ring-2 ring-primary/30 shadow-md'
                    : 'border-border hover:border-border-hover',
                )}
              >
                {/* 封面图 */}
                <div className="aspect-[3/2] bg-bg-subtle">
                  <ThemeCover
                    src={preset.cover}
                    alt={preset.name}
                    gradientFrom={preset.gradientFrom}
                    gradientTo={preset.gradientTo}
                  />
                </div>

                {/* 主题信息 */}
                <div className="p-2 text-left">
                  <div
                    className={clsx(
                      'text-sm font-medium truncate',
                      isActive ? 'text-primary' : 'text-text',
                    )}
                  >
                    {preset.name}
                  </div>
                  <div className="text-xs text-text-muted truncate">{preset.description}</div>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
