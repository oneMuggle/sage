/**
 * 主题选择器 — 6 个预设主题卡片
 */

import { clsx } from 'clsx';

import { useTheme } from '../../app/providers/useTheme';
import { themePresets } from '../../entities/theme/presets';

/** 从主题颜色中提取 primary 色用于预览圆点 */
function getPreviewColor(colors: { primary: string }): string {
  return colors.primary;
}

export function ThemeSelector() {
  const { presetId, setPresetId, resolved } = useTheme();

  return (
    <div className="grid grid-cols-3 gap-3">
      {themePresets.map((preset) => {
        const isActive = preset.id === presetId;
        const colors = resolved === 'dark' ? preset.darkColors : preset.colors;
        const previewColor = getPreviewColor(colors);

        return (
          <button
            key={preset.id}
            onClick={() => setPresetId(preset.id)}
            className={clsx(
              'flex items-center gap-2.5 px-3 py-2.5 rounded-radius-md border text-left transition-all',
              isActive
                ? 'border-primary bg-primary/5 ring-1 ring-primary/30'
                : 'border-border hover:border-border-hover hover:bg-bg-hover',
            )}
            type="button"
          >
            {/* 颜色预览圆点 */}
            <div
              className="w-6 h-6 rounded-full flex-shrink-0 border border-border"
              style={{ backgroundColor: previewColor }}
            />
            <div className="min-w-0">
              <div className={clsx('text-sm font-medium', isActive ? 'text-primary' : 'text-text')}>
                {preset.name}
              </div>
              <div className="text-[11px] text-text-muted truncate">{preset.description}</div>
            </div>
          </button>
        );
      })}
    </div>
  );
}
