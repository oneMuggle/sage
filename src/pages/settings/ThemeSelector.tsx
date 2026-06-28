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

export function ThemeSelector() {
  const { t } = useI18n();
  const { cssThemes, activeSource, setActiveCssTheme, refreshCssThemes } = useTheme();
  const [modalOpen, setModalOpen] = useState(false);

  function handleNewTheme() {
    setModalOpen(true);
  }

  async function handleDeleteTheme(theme: ThemeCssPayload) {
    if (!confirm(`确定要删除主题 "${theme.name}" 吗？`)) return;

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
          <button
            type="button"
            onClick={handleNewTheme}
            className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10 rounded-radius-md transition-colors"
          >
            <Plus size={14} />
            新建自定义
          </button>
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
