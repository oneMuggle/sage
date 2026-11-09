/**
 * BatchToolsTab — rules sub-tab C: bulk audit tooling + navigation card.
 *
 * Part of the 2026-11 IA redesign: the old `renderRulesTab()` in `Office.tsx`
 * stacked six panels vertically; this sub-tab isolates the bulk-audit use
 * case so users looking for "run audit across many files" land in one place
 * instead of wading through rule CRUD and AI audit panels.
 *
 * Content:
 * - `WordBatchAuditPanel`: the glob + rule-pack bulk audit UI (unchanged).
 * - A guide card that nudges users back to the documents tab when they have
 *   no batch-friendly setup yet (mirrors the card that used to live at the
 *   bottom of the old rules tab).
 */

import { useI18n } from '../../../shared/lib/i18n';
import { WordBatchAuditPanel } from '../WordBatchAuditPanel';

interface BatchToolsTabProps {
  workspacePath: string;
  /** Called by the guide card to jump users back to the documents tab. */
  onGoToDocuments: () => void;
}

export function BatchToolsTab({ workspacePath, onGoToDocuments }: BatchToolsTabProps) {
  const { t } = useI18n();

  return (
    <div className="space-y-4">
      <WordBatchAuditPanel workspacePath={workspacePath} />

      <article
        className="rounded-lg border border-border bg-bg-subtle p-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"
        data-testid="office-batch-tools-guide"
      >
        <div>
          <h3 className="text-sm font-medium text-text">{t('office.rules.guide.title')}</h3>
          <p className="text-xs text-muted mt-1">{t('office.rules.guide.body')}</p>
        </div>
        <button
          type="button"
          onClick={onGoToDocuments}
          data-testid="office-batch-tools-goto-documents"
          className="shrink-0 px-3 py-1.5 rounded text-sm border border-border text-text-secondary hover:bg-bg-hover"
        >
          {t('office.rules.guide.action')}
        </button>
      </article>
    </div>
  );
}
