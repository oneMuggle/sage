// src/features/office/rules/ConflictDialog.tsx
import { useI18n } from '../../../shared/lib/i18n';

import type { RuleConflict } from './ruleTypes';

export interface ConflictDialogProps {
  conflicts: RuleConflict[];
  ruleNameById: (id: string) => string;
  onClose: () => void;
}

export function ConflictDialog({ conflicts, ruleNameById, onClose }: ConflictDialogProps) {
  const { t } = useI18n();

  return (
    <div
      role="dialog"
      aria-modal="true"
      data-testid="rules-conflict-dialog"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
    >
      <div className="max-h-[80vh] w-full max-w-lg overflow-auto rounded border border-border bg-surface p-5 shadow-lg">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-medium text-text">{t('office.rules.conflict.title')}</h3>
          <button
            type="button"
            data-testid="rules-conflict-close"
            className="rounded border border-border px-3 py-1 text-xs text-text-secondary hover:bg-bg-hover"
            onClick={onClose}
          >
            {t('office.rules.conflict.close')}
          </button>
        </div>
        <ul className="space-y-3">
          {conflicts.map((conflict, index) => (
            <li
              key={index}
              className="rounded border border-border bg-bg-subtle p-3"
              data-testid={`rules-conflict-item-${index}`}
            >
              <p className="text-xs font-medium text-text">{conflict.message}</p>
              <p className="mt-1 text-xs text-text-secondary">
                {t('office.rules.conflict.rules')}: {conflict.ruleIds.map(ruleNameById).join(', ')}
              </p>
              {conflict.suggestion ? (
                <p className="mt-1 text-xs text-text-secondary">
                  {t('office.rules.conflict.suggestion')}: {conflict.suggestion}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
