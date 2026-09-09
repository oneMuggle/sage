/**
 * OfficeDocumentList — workspace history (Phase 1.3, plan §4.1.4 step 16).
 *
 * Lists previously read/generated office documents in the current workspace.
 *
 * M0 Task 6 (2026-07-23): rewired actions to the M0 management set:
 *   - Save As (native dialog → copy managed file to chosen path)
 *   - Open (shell.openPath on the managed file)
 *   - Show in Folder (shell.showItemInFolder)
 * The Phase 1.3 delete action was REMOVED. The brief is explicit: do
 * not expose a permanent delete action from the management view.
 *
 * Office parity batch 1 (item 1.7): the soft-delete lifecycle is now
 * user-facing. `variant="live"` rows carry 归档 (archive) + 历史版本
 * (snapshots) actions; `variant="archived"` rows carry 恢复 (restore).
 * The destructive delete stays out of the UI.
 */

import { Archive, ArchiveRestore, FolderOpen, FileSpreadsheet, FileText, History, Presentation, Save } from 'lucide-react';

import type { OfficeDocType, OfficeDocumentSummary } from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';

const DOC_TYPE_ICONS: Record<OfficeDocType, React.ReactNode> = {
  ppt: <Presentation className="w-4 h-4" />,
  word: <FileText className="w-4 h-4" />,
  excel: <FileSpreadsheet className="w-4 h-4" />,
  pdf: <FileText className="w-4 h-4" />,
};

const DOC_TYPE_LABELS: Record<OfficeDocType, string> = {
  ppt: 'PPT',
  word: 'Word',
  excel: 'Excel',
  pdf: 'PDF',
};

export interface OfficeDocumentListProps {
  documents: OfficeDocumentSummary[];
  loading: boolean;
  /** Which slice of the lifecycle this list renders — drives the row actions. */
  variant?: 'live' | 'archived';
  /** Native Save As dialog → copy managed file to chosen path. */
  onSaveAs?: (docId: string) => void | Promise<void>;
  /** shell.openPath on the managed file. */
  onOpen?: (docId: string) => void | Promise<void>;
  /** shell.showItemInFolder on the managed file. */
  onShowInFolder?: (docId: string) => void | Promise<void>;
  /** Soft-delete the row (variant="live" only). */
  onArchive?: (docId: string) => void | Promise<void>;
  /** Un-archive the row (variant="archived" only). */
  onRestore?: (docId: string) => void | Promise<void>;
  /** Open the 历史版本 (snapshots) panel for the row. */
  onViewSnapshots?: (docId: string) => void | Promise<void>;
}

export function OfficeDocumentList({
  documents,
  loading,
  variant = 'live',
  onSaveAs,
  onOpen,
  onShowInFolder,
  onArchive,
  onRestore,
  onViewSnapshots,
}: OfficeDocumentListProps) {
  const { t } = useI18n();
  // Status labels are built inside the component so the translated
  // strings track the active locale (module-level maps can't call t()).
  const statusLabels: Record<OfficeDocumentSummary['status'], string> = {
    parsed: t('office.doc.status.parsed'),
    generated: t('office.doc.status.generated'),
    edited: t('office.doc.status.edited'),
  };

  if (loading) {
    return <div className="text-sm text-muted p-4 text-center">{t('common.loading')}</div>;
  }
  if (documents.length === 0) {
    return (
      <div className="text-sm text-muted p-4 text-center border border-dashed border-border rounded-lg">
        {t('office.doc.empty')}
      </div>
    );
  }
  return (
    <ul className="space-y-2" data-testid="office-document-list">
      {documents.map((doc) => (
        <li
          key={doc.id}
          className="flex items-center gap-3 p-3 border border-border rounded-lg bg-surface"
        >
          <div className="text-muted">{DOC_TYPE_ICONS[doc.doc_type]}</div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-text truncate">
              {doc.original_filename ?? doc.generated_filename}
            </div>
            <div className="text-xs text-muted flex items-center gap-2">
              <span>{DOC_TYPE_LABELS[doc.doc_type]}</span>
              <span>·</span>
              <span>{statusLabels[doc.status]}</span>
              <span>·</span>
              <span>{(doc.metadata.file_size_bytes / 1024).toFixed(1)} KB</span>
              <span>·</span>
              <span>{new Date(doc.created_at).toLocaleString()}</span>
              {doc.archived_at != null && (
                <>
                  <span>·</span>
                  <span>
                    {t('office.doc.archivedAt')} {new Date(doc.archived_at).toLocaleString()}
                  </span>
                </>
              )}
            </div>
          </div>
          <div className="flex items-center gap-1">
            {variant === 'live' && onArchive && (
              <button
                type="button"
                onClick={() => void onArchive(doc.id)}
                className="p-1.5 rounded text-muted hover:text-primary hover:bg-primary/10 transition-colors"
                aria-label={t('office.doc.archive')}
              >
                <Archive className="w-4 h-4" />
              </button>
            )}
            {variant === 'archived' && onRestore && (
              <button
                type="button"
                onClick={() => void onRestore(doc.id)}
                className="p-1.5 rounded text-muted hover:text-primary hover:bg-primary/10 transition-colors"
                aria-label={t('office.doc.restore')}
              >
                <ArchiveRestore className="w-4 h-4" />
              </button>
            )}
            {onViewSnapshots && (
              <button
                type="button"
                onClick={() => void onViewSnapshots(doc.id)}
                className="p-1.5 rounded text-muted hover:text-primary hover:bg-primary/10 transition-colors"
                aria-label={t('office.doc.snapshots')}
              >
                <History className="w-4 h-4" />
              </button>
            )}
            {onSaveAs && (
              <button
                type="button"
                onClick={() => void onSaveAs(doc.id)}
                className="p-1.5 rounded text-muted hover:text-primary hover:bg-primary/10 transition-colors"
                aria-label={t('office.doc.saveAs')}
              >
                <Save className="w-4 h-4" />
              </button>
            )}
            {onOpen && (
              <button
                type="button"
                onClick={() => void onOpen(doc.id)}
                className="p-1.5 rounded text-muted hover:text-primary hover:bg-primary/10 transition-colors"
                aria-label={t('office.doc.open')}
              >
                <FileText className="w-4 h-4" />
              </button>
            )}
            {onShowInFolder && (
              <button
                type="button"
                onClick={() => void onShowInFolder(doc.id)}
                className="p-1.5 rounded text-muted hover:text-primary hover:bg-primary/10 transition-colors"
                aria-label={t('office.doc.showInFolder')}
              >
                <FolderOpen className="w-4 h-4" />
              </button>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
