import { useEffect } from 'react';

import { useI18n, type TranslationKey } from '../../../shared/lib/i18n';

export type FloatingActionKind = 'rewrite' | 'chat' | 'edit' | 'audit';

export interface FloatingActionBarProps {
  anchorRect: { top: number; left: number; width: number } | null;
  canApply: boolean;
  onAction: (kind: FloatingActionKind) => void;
  onDismiss: () => void;
}

const ACTIONS: { kind: FloatingActionKind; labelKey: TranslationKey; needsDocument: boolean }[] = [
  { kind: 'rewrite', labelKey: 'office.ai.selection.rewrite', needsDocument: false },
  { kind: 'chat', labelKey: 'office.ai.selection.chat', needsDocument: false },
  { kind: 'edit', labelKey: 'office.ai.selection.edit', needsDocument: true },
  { kind: 'audit', labelKey: 'office.ai.selection.audit', needsDocument: true },
];

export function FloatingActionBar({
  anchorRect,
  canApply,
  onAction,
  onDismiss,
}: FloatingActionBarProps): JSX.Element | null {
  const { t } = useI18n();

  useEffect(() => {
    if (!anchorRect) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onDismiss();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [anchorRect, onDismiss]);

  if (!anchorRect) return null;

  return (
    <div
      data-testid="office-floating-action-bar"
      role="toolbar"
      aria-label={t('office.ai.selection.toolbarLabel')}
      className="fixed z-40 flex items-center gap-1 rounded-lg border border-border bg-surface px-1 py-1 shadow-lg"
      style={{ top: Math.max(anchorRect.top - 44, 8), left: Math.max(anchorRect.left, 8) }}
      onMouseDown={(event) => event.preventDefault()}
    >
      {ACTIONS.map((action) => (
        <button
          key={action.kind}
          type="button"
          data-testid={`office-floating-action-${action.kind}`}
          disabled={action.needsDocument && !canApply}
          className="rounded px-2 py-1 text-xs hover:bg-surface-hover disabled:opacity-40"
          onClick={() => onAction(action.kind)}
        >
          {t(action.labelKey)}
        </button>
      ))}
      <button
        type="button"
        data-testid="office-floating-action-dismiss"
        className="rounded px-2 py-1 text-xs text-text-muted hover:bg-surface-hover"
        onClick={onDismiss}
      >
        {t('office.ai.selection.dismiss')}
      </button>
    </div>
  );
}
