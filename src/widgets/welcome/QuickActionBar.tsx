import { clsx } from 'clsx';
import { type ReactNode } from 'react';

import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

export interface QuickAction {
  id: 'feedback' | 'github' | 'webui' | 'docs';
  icon: ReactNode;
  labelKey: TranslationKey;
  descKey?: TranslationKey;
  onClick: () => void;
  badge?: { text: string; variant: 'success' | 'warning' | 'error' };
}

interface QuickActionBarProps {
  actions: QuickAction[];
}

export function formatQuickActionsMarkdown(actions: ReadonlyArray<QuickAction>): string {
  const lines = ['# 欢迎页快捷操作栏 (Quick Action Bar)', '', `- **操作总数**: ${actions.length}`];
  if (actions.length === 0) {
    lines.push('', '_暂无快捷操作_');
  } else {
    lines.push('', '## 快捷操作');
    for (const a of actions) {
      const badge = a.badge ? ` [${a.badge.variant}: ${a.badge.text}]` : '';
      lines.push(`- **${a.id}** (\`${a.labelKey}\`)${badge}`);
    }
  }
  return lines.join('\n');
}

export function formatQuickActionsJson(actions: ReadonlyArray<QuickAction>): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      total: actions.length,
      actions: actions.map((a) => ({
        id: a.id,
        labelKey: a.labelKey,
        descKey: a.descKey ?? null,
        badge: a.badge ?? null,
      })),
    },
    null,
    2,
  );
}

const badgeColorMap: Record<NonNullable<QuickAction['badge']>['variant'], string> = {
  success: 'bg-success/15 text-success',
  warning: 'bg-warning/15 text-warning',
  error: 'bg-error/15 text-error',
};

export function QuickActionBar({ actions }: QuickActionBarProps) {
  const { t } = useI18n();

  /* v8 ignore start */

  /* v8 ignore stop */

  return (
    <div
      className="flex items-center justify-center gap-2 flex-wrap"
      role="toolbar"
      aria-label="quick actions"
    >
      {actions.map((action) => (
        <button
          key={action.id}
          type="button"
          onClick={action.onClick}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-radius-sm border border-border bg-surface hover:bg-bg-hover text-xs text-text-secondary hover:text-text transition-colors focus:outline-none focus:ring-2 focus:ring-primary/30"
          aria-label={action.descKey ? t(action.descKey) : t(action.labelKey)}
        >
          <span aria-hidden="true">{action.icon}</span>
          <span>{t(action.labelKey)}</span>
          {action.badge && (
            <span
              data-testid="quick-action-badge"
              className={clsx(
                'ml-1 px-1.5 py-0.5 rounded text-ui-xs font-medium',
                badgeColorMap[action.badge.variant],
              )}
            >
              {action.badge.text}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
