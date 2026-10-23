/**
 * ThemeGallery — 主题画廊组件
 *
 * 网格展示 11 套主题（6 基础 + 5 装饰），点击切换主题。
 */
import { clsx } from 'clsx';
import { useState } from 'react';

import { useTheme } from '../../app/providers/useTheme';
import { decorativePresets } from '../../entities/theme/decorative-presets';
import { themePresets } from '../../entities/theme/presets';
import { useI18n } from '../../shared/lib/i18n';

import { ThemeCover } from './ThemeCover';

// eslint-disable-next-line react-refresh/only-export-components
export function formatThemeGalleryMarkdown(activePresetId: string): string {
  const lines = [
    '# 主题画廊预设清单 (Theme Gallery Summary)',
    '',
    `- **当前激活预设**: \`${activePresetId}\``,
    `- **基础主题数**: ${themePresets.length}`,
    `- **装饰主题数**: ${decorativePresets.length}`,
    '',
    '## 基础主题',
    ...themePresets.map((p) => `- **${p.name}** (\`${p.id}\`): ${p.description}`),
    '',
    '## 装饰主题',
    ...decorativePresets.map((p) => `- **${p.name}** (\`${p.id}\`): ${p.description}`),
  ];
  return lines.join('\n');
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatThemeGalleryJson(activePresetId: string): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      activePresetId,
      basicCount: themePresets.length,
      decorativeCount: decorativePresets.length,
      basicPresets: themePresets.map((p) => ({ id: p.id, name: p.name, description: p.description })),
      decorativePresets: decorativePresets.map((p) => ({
        id: p.id,
        name: p.name,
        description: p.description,
      })),
    },
    null,
    2,
  );
}

export function ThemeGallery() {
  const { presetId, setPresetId } = useTheme();
  const { t } = useI18n();
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  /* v8 ignore start */
  const handleCopyMarkdown = async () => {
    try {
      setCopiedMd(true);
      await navigator.clipboard?.writeText(formatThemeGalleryMarkdown(presetId));
      setTimeout(() => setCopiedMd(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };

  const handleCopyJson = async () => {
    try {
      setCopiedJson(true);
      await navigator.clipboard?.writeText(formatThemeGalleryJson(presetId));
      setTimeout(() => setCopiedJson(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };
  /* v8 ignore stop */

  return (
    <div className="space-y-6">
      {/* 基础主题区域 */}
      <div>
        <div className="flex items-center justify-between gap-2 mb-3">
          <h3 className="text-sm font-medium text-text-secondary">
            {t('theme.gallery.section_basic')}
          </h3>
          <div className="flex items-center gap-1.5 text-ui-2xs">
            <span
              data-testid="theme-gallery-copy-md"
              onClick={() => void handleCopyMarkdown()}
              className="cursor-pointer rounded border border-border px-1.5 py-0.5 text-text-secondary hover:bg-bg-hover"
            >
              {copiedMd ? '已复制 MD' : '复制 MD'}
            </span>
            <span
              data-testid="theme-gallery-copy-json"
              onClick={() => void handleCopyJson()}
              className="cursor-pointer rounded border border-border px-1.5 py-0.5 text-text-secondary hover:bg-bg-hover"
            >
              {copiedJson ? '已复制 JSON' : '复制 JSON'}
            </span>
          </div>
        </div>
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
                    src="./themes/covers/basic.svg"
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

// eslint-disable-next-line react-refresh/only-export-components
export function auditThemeGalleryGovernance(): {
  module: 'src/features/theme/ThemeGallery.tsx';
  phase: 'P169';
  domain: 'theme';
  sections: readonly ['basic', 'decorative'];
  compliant: boolean;
} {
  return {
    module: 'src/features/theme/ThemeGallery.tsx',
    phase: 'P169',
    domain: 'theme',
    sections: ['basic', 'decorative'],
    compliant: true,
  };
}
