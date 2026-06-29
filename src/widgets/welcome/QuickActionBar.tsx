import type { ReactNode } from 'react';
import { clsx } from 'clsx';

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

const badgeColorMap: Record<NonNullable<QuickAction['badge']>['variant'], string> = {
  success: 'bg-success/15 text-success',
  warning: 'bg-warning/15 text-warning',
  error: 'bg-error/15 text-error',
};

export function QuickActionBar({ actions }: QuickActionBarProps) {
  const { t } = useI18n();

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
                'ml-1 px-1.5 py-0.5 rounded text-[10px] font-medium',
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
