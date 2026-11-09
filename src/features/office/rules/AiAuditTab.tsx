/**
 * AiAuditTab — rules sub-tab B: audit the current document.
 *
 * Part of the 2026-11 IA redesign. The old rules tab offered three separate
 * "audit" entry points (rule-group audit inside `RulesWorkspace`, the
 * spec-book audit inside `OfficeAiAssistantPanel`, and the bulk glob audit),
 * with overlapping file pickers. This sub-tab narrows the surface to a
 * single concept: *audit the document you are looking at*.
 *
 * The current document comes from the shared office workspace store
 * (populated by the document tab's preview handler — see plan §Section 1).
 * Its managed path is pre-filled into the audit panel so the user does not
 * have to re-pick a file they already opened.
 */

import { useOfficeWorkspaceStore } from '../../../entities/office/officeWorkspaceStore';
import { useI18n } from '../../../shared/lib/i18n';
import { OfficeAiAssistantPanel } from '../OfficeAiAssistantPanel';
import { officeDocumentPath } from '../officeDocumentPath';

const DOC_TYPE_LABELS: Record<string, string> = {
  ppt: 'PPT',
  word: 'Word',
  excel: 'Excel',
  pdf: 'PDF',
};

interface AiAuditTabProps {
  workspacePath: string;
}

export function AiAuditTab({ workspacePath }: AiAuditTabProps) {
  const { t } = useI18n();
  const activeDocument = useOfficeWorkspaceStore((state) => state.activeDocument);
  const documentPath = activeDocument ? officeDocumentPath(activeDocument) : null;

  return (
    <div className="space-y-4">
      {/* Current document context — mirrors the AI sidebar chip so both
          surfaces agree on which document the audit will target. */}
      <div
        className="flex items-center gap-2 rounded-lg border border-border bg-bg-subtle px-3 py-2"
        data-testid="office-ai-audit-current-doc"
      >
        {activeDocument ? (
          <>
            <span className="shrink-0 text-xs text-muted">
              {DOC_TYPE_LABELS[activeDocument.doc_type] ?? activeDocument.doc_type}
            </span>
            <span className="min-w-0 truncate text-sm text-text">
              {activeDocument.original_filename ??
                activeDocument.generated_filename ??
                activeDocument.id}
            </span>
            {documentPath && (
              <span className="min-w-0 flex-1 truncate text-xs text-muted" title={documentPath}>
                {documentPath}
              </span>
            )}
          </>
        ) : (
          <span className="text-xs text-muted">
            {t('office.rules.aiAudit.noDocument')}
          </span>
        )}
      </div>

      <OfficeAiAssistantPanel workspacePath={workspacePath} initialFilePath={documentPath} />
    </div>
  );
}
