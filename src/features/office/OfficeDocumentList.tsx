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
 *
 * Round 3 (N5): batch operations. Rows in either variant carry a
 * checkbox; a toolbar above the list offers 批量归档 (live) /
 * 批量恢复 (archived) over the selection. The sequential API loop +
 * single refetch live in useOfficeDocuments (batchArchive/batchRestore);
 * this component owns only the selection state, the progress/summary
 * toasts, and clearing the selection after the action. Row-level single
 * actions are unchanged.
 */

import { Archive, ArchiveRestore, FolderOpen, FileSpreadsheet, FileText, History, Presentation, Save } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

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

/** Outcome of a batch archive/restore — drives the summary toast (N5). */
export interface OfficeBatchResult {
  /** Doc ids whose archive/restore succeeded. */
  succeeded: string[];
  /** Doc ids whose archive/restore failed — counted in the summary. */
  failed: string[];
}

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
  /**
   * Batch-archive the selected live rows (round-3 N5, variant="live").
   * Resolves with the per-item outcome so the toolbar can show a
   * counted summary toast. When absent the checkboxes/toolbar hide.
   */
  onBatchArchive?: (docIds: string[]) => OfficeBatchResult | Promise<OfficeBatchResult>;
  /**
   * Batch-restore the selected archived rows (round-3 N5,
   * variant="archived"). Same contract as onBatchArchive.
   */
  onBatchRestore?: (docIds: string[]) => OfficeBatchResult | Promise<OfficeBatchResult>;
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
  onBatchArchive,
  onBatchRestore,
}: OfficeDocumentListProps) {
  const { t } = useI18n();
  // Round-3 N5: selection state for the batch actions. All hooks stay
  // above the loading/empty early returns (rules-of-hooks).
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [batchBusy, setBatchBusy] = useState(false);

  // Prune ids that left the current slice — the parent refetches after
  // every action, and the live↔archived toggle reuses this component
  // instance with a different documents array.
  useEffect(() => {
    setSelected((prev) => {
      if (prev.size === 0) return prev;
      const ids = new Set(documents.map((d) => d.id));
      const next = new Set([...prev].filter((id) => ids.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [documents]);

  const batchAction = variant === 'archived' ? onBatchRestore : onBatchArchive;

  const toggleDoc = (docId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(docId)) {
        next.delete(docId);
      } else {
        next.add(docId);
      }
      return next;
    });
  };

  const allSelected = documents.length > 0 && documents.every((d) => selected.has(d.id));
  const toggleAll = () => {
    setSelected(allSelected ? new Set() : new Set(documents.map((d) => d.id)));
  };

  const handleBatch = async () => {
    if (!batchAction || selected.size === 0 || batchBusy) return;
    // Freeze the selection up front — the refetch inside batchAction
    // prunes `selected` via the effect above.
    const docIds = [...selected];
    setBatchBusy(true);
    // Progress toast: the same toast id transitions 开始… → 完成 N 项.
    const toastId = toast.loading(t('office.batch.start'));
    try {
      const { succeeded, failed } = await batchAction(docIds);
      if (failed.length === 0) {
        toast.success(t('office.batch.done').replace('{n}', String(succeeded.length)), {
          id: toastId,
        });
      } else {
        toast.error(
          t('office.batch.doneWithFailures')
            .replace('{n}', String(succeeded.length))
            .replace('{m}', String(failed.length)),
          { id: toastId },
        );
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.batch.failed')}: ${msg}`, { id: toastId });
    } finally {
      setBatchBusy(false);
      // Clear the selection after the action regardless of outcome —
      // failed rows are reported in the summary and can be retried via
      // the per-row action.
      setSelected(new Set());
    }
  };

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

  const batchLabel = variant === 'archived' ? t('office.batch.restore') : t('office.batch.archive');
  const batchTestId = variant === 'archived' ? 'office-batch-restore' : 'office-batch-archive';

  return (
    <div>
      {batchAction && (
        <div className="flex items-center gap-3 mb-2" data-testid="office-batch-bar">
          <label className="flex items-center gap-1.5 text-xs text-muted cursor-pointer">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={toggleAll}
              disabled={batchBusy}
              data-testid="office-batch-select-all"
              aria-label={t('office.batch.selectAll')}
              className="w-4 h-4"
            />
            {t('office.batch.selectAll')}
          </label>
          <span className="text-xs text-muted" data-testid="office-batch-count">
            {t('office.batch.selectedCount').replace('{n}', String(selected.size))}
          </span>
          <button
            type="button"
            onClick={() => void handleBatch()}
            disabled={selected.size === 0 || batchBusy}
            data-testid={batchTestId}
            className="ml-auto px-3 py-1.5 rounded text-sm border border-primary text-primary hover:bg-primary/10 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {batchLabel}
          </button>
        </div>
      )}
      <ul className="space-y-2" data-testid="office-document-list">
        {documents.map((doc) => (
          <li
            key={doc.id}
            className="flex items-center gap-3 p-3 border border-border rounded-lg bg-surface"
          >
            {batchAction && (
              <input
                type="checkbox"
                checked={selected.has(doc.id)}
                onChange={() => toggleDoc(doc.id)}
                disabled={batchBusy}
                data-testid={`office-doc-select-${doc.id}`}
                aria-label={t('office.batch.selectRow')}
                className="w-4 h-4 shrink-0"
              />
            )}
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
    </div>
  );
}
