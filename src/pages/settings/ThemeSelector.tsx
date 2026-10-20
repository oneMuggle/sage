/**
 * 主题选择器 — 画廊视图 + CSS 自定义主题
 */

import { clsx } from 'clsx';
import { Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';

import { useTheme } from '../../app/providers/useTheme';
import { CssThemeModal } from '../../features/theme/CssThemeModal';
import { ThemeGallery } from '../../features/theme/ThemeGallery';
import type { ThemeCssPayload } from '../../features/theme/themeCssTypes';
import { themeCssClient } from '../../shared/api/themeCssClient';
import { useI18n } from '../../shared/lib/i18n';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';

export function formatThemeSelectorMarkdown(params: {
  activeKind: string;
  activeId: string;
  cssThemes: ReadonlyArray<ThemeCssPayload>;
}): string {
  const lines = [
    '# 主题选择器与自定义 CSS 清单 (Theme Selector Summary)',
    '',
    `- **当前激活来源**: \`${params.activeKind}\` (\`${params.activeId}\`)`,
    `- **自定义 CSS 主题数**: ${params.cssThemes.length}`,
  ];
  if (params.cssThemes.length === 0) {
    lines.push('', '_尚未创建自定义主题_');
  } else {
    lines.push('', '## 自定义 CSS 主题明细');
    for (const t of params.cssThemes) {
      lines.push(`- **${t.name}** (\`${t.id}\`, \`${t.appearance}\`)`);
    }
  }
  return lines.join('\n');
}

export function formatThemeSelectorJson(params: {
  activeKind: string;
  activeId: string;
  cssThemes: ReadonlyArray<ThemeCssPayload>;
}): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      activeKind: params.activeKind,
      activeId: params.activeId,
      cssCount: params.cssThemes.length,
      cssThemes: params.cssThemes.map((t) => ({
        id: t.id,
        name: t.name,
        appearance: t.appearance,
      })),
    },
    null,
    2,
  );
}

export function ThemeSelector() {
  const { t } = useI18n();
  const { cssThemes, activeSource, setActiveCssTheme, refreshCssThemes } = useTheme();
  const [modalOpen, setModalOpen] = useState(false);
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  function handleNewTheme() {
    setModalOpen(true);
  }

  async function handleDeleteTheme(theme: ThemeCssPayload) {
    const ok = await confirmDialog({ title: '删除自定义主题', message: `确定要删除主题 "${theme.name}" 吗？`, danger: true });
    if (!ok) return;

    try {
      await themeCssClient.delete(theme.id);
      await refreshCssThemes();
    } catch (error) {
      console.error('[ThemeSelector] Failed to delete theme:', error);
    }
  }

  async function handleModalSaved() {
    await refreshCssThemes();
  }

  /* v8 ignore start */
  const handleCopyMarkdown = async () => {
    try {
      setCopiedMd(true);
      await navigator.clipboard?.writeText(
        formatThemeSelectorMarkdown({
          activeKind: activeSource.kind,
          activeId: activeSource.id,
          cssThemes,
        }),
      );
      setTimeout(() => setCopiedMd(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };

  const handleCopyJson = async () => {
    try {
      setCopiedJson(true);
      await navigator.clipboard?.writeText(
        formatThemeSelectorJson({
          activeKind: activeSource.kind,
          activeId: activeSource.id,
          cssThemes,
        }),
      );
      setTimeout(() => setCopiedJson(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };
  /* v8 ignore stop */

  return (
    <div className="space-y-6">
      {/* 画廊视图（基础 + 装饰主题） */}
      <div>
        <h3 className="text-sm font-medium text-text-secondary mb-3">
          {t('settings.section.theme')}
        </h3>
        <ThemeGallery />
      </div>

      {/* CSS 自定义主题 */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-text-secondary">自定义 CSS 主题</h3>
          <div className="flex items-center gap-1.5">
            <span
              data-testid="theme-selector-copy-md"
              onClick={() => void handleCopyMarkdown()}
              className="cursor-pointer rounded border border-border px-1.5 py-0.5 text-ui-2xs text-text-secondary hover:bg-bg-hover"
            >
              {copiedMd ? '已复制 MD' : '复制 MD'}
            </span>
            <span
              data-testid="theme-selector-copy-json"
              onClick={() => void handleCopyJson()}
              className="cursor-pointer rounded border border-border px-1.5 py-0.5 text-ui-2xs text-text-secondary hover:bg-bg-hover"
            >
              {copiedJson ? '已复制 JSON' : '复制 JSON'}
            </span>
            <button
              type="button"
              onClick={handleNewTheme}
              className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10 rounded-radius-md transition-colors"
            >
              <Plus size={14} />
              新建自定义
            </button>
          </div>
        </div>

        {cssThemes.length === 0 ? (
          <div className="text-center py-8 text-text-muted text-sm border border-dashed border-border rounded-radius-md">
            尚未创建自定义主题
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-3">
            {cssThemes.map((theme) => {
              const isActive = activeSource.kind === 'css' && activeSource.id === theme.id;

              return (
                <div
                  key={theme.id}
                  className={clsx(
                    'relative group rounded-radius-md border overflow-hidden transition-all',
                    isActive
                      ? 'border-primary ring-1 ring-primary/30'
                      : 'border-border hover:border-border-hover',
                  )}
                >
                  {/* 封面图或占位符 */}
                  <button
                    type="button"
                    onClick={() => setActiveCssTheme(theme.id)}
                    className="w-full"
                  >
                    {theme.cover ? (
                      <img
                        src={theme.cover}
                        alt={theme.name}
                        className="w-full h-20 object-cover"
                      />
                    ) : (
                      <div className="w-full h-20 bg-bg-subtle flex items-center justify-center text-text-muted text-xs">
                        {theme.appearance === 'dark' ? '深色' : '浅色'}
                      </div>
                    )}
                  </button>

                  {/* 主题名称和操作按钮 */}
                  <div className="px-2 py-1.5 flex items-center justify-between gap-1">
                    <div
                      className={clsx(
                        'text-sm font-medium truncate flex-1',
                        isActive ? 'text-primary' : 'text-text',
                      )}
                    >
                      {theme.name}
                    </div>
                    <button
                      type="button"
                      onClick={() => handleDeleteTheme(theme)}
                      className="opacity-0 group-hover:opacity-100 p-1 text-text-muted hover:text-error transition-opacity"
                      title="删除主题"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* 模态框 */}
      <CssThemeModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSaved={handleModalSaved}
      />
    </div>
  );
}
