/**
 * OfficeSnapshotPanel — 历史版本 (pre-edit snapshots) panel (parity batch 1, item 1.7).
 *
 * Opened from a document row's History action. Lists the snapshot files
 * the backend captured before each edit
 * (`<managed_dir>/.snapshots/<ms>-<generated_filename>`, served by
 * GET /office/doc/{doc_id}/snapshots) with captured time + size, and a
 * per-item 恢复到此版本 action backed by
 * POST /office/doc/{doc_id}/snapshots/{snapshot_id}/restore.
 *
 * The restore is destructive (it overwrites the managed file's bytes),
 * so it runs behind a two-step inline confirm: the first click arms the
 * row (确认恢复 / 取消), the second click commits. After a successful
 * restore the parent refreshes the preview + document list via
 * `onRestored`.
 */

import { History, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { officeApi } from '../../shared/api/officeApi';
import type { OfficeDocumentSummary, OfficeSnapshotMeta } from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';

export interface OfficeSnapshotPanelProps {
  /** The document whose snapshots are listed. */
  doc: OfficeDocumentSummary;
  onClose: () => void;
  /** Called after a successful restore so the parent can refresh preview + list. */
  onRestored: (docId: string) => void | Promise<void>;
}

export function OfficeSnapshotPanel({ doc, onClose, onRestored }: OfficeSnapshotPanelProps) {
  const { t } = useI18n();
  const [snapshots, setSnapshots] = useState<OfficeSnapshotMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Which row is armed for restore (two-step confirm). Null = none armed.
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [restoring, setRestoring] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setConfirmingId(null);
    officeApi
      .listSnapshots(doc.id)
      .then((res) => {
        if (cancelled) return;
        setSnapshots(res.snapshots);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [doc.id]);

  const handleRestore = async (snapshotId: string) => {
    setRestoring(true);
    try {
      await officeApi.restoreSnapshot(doc.id, snapshotId);
      toast.success(t('office.snapshot.restoreSuccess'));
      setConfirmingId(null);
      await onRestored(doc.id);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.snapshot.restoreFailed')}: ${msg}`);
    } finally {
      setRestoring(false);
    }
  };

  return (
    <div
      className="border border-border rounded-lg bg-surface overflow-hidden"
      data-testid="office-snapshot-panel"
    >
      <div className="flex items-center gap-2 px-4 py-3 border-b border-border bg-bg-subtle">
        <History className="w-4 h-4" />
        <span className="font-medium text-sm">{t('office.snapshot.title')}</span>
        <span className="text-xs text-muted truncate">
          {doc.original_filename ?? doc.generated_filename}
        </span>
        <button
          type="button"
          onClick={onClose}
          className="ml-auto p-1 rounded text-muted hover:text-text hover:bg-bg-hover transition-colors"
          aria-label={t('office.snapshot.close')}
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="p-4 max-h-72 overflow-y-auto">
        {loading && <div className="text-sm text-muted text-center">{t('common.loading')}</div>}
        {!loading && error && <div className="text-sm text-error">{error}</div>}
        {!loading && !error && snapshots.length === 0 && (
          <div className="text-sm text-muted text-center">{t('office.snapshot.empty')}</div>
        )}
        {!loading && !error && snapshots.length > 0 && (
          <ul className="space-y-2">
            {snapshots.map((snap) => (
              <li
                key={snap.snapshot_id}
                className="flex items-center gap-3 p-2 border border-border rounded"
              >
                <div className="flex-1 min-w-0 text-xs text-muted">
                  <div className="text-text text-sm truncate">{snap.snapshot_id}</div>
                  <div className="flex items-center gap-2">
                    <span>{new Date(snap.created_at).toLocaleString()}</span>
                    <span>·</span>
                    <span>{(snap.size_bytes / 1024).toFixed(1)} KB</span>
                  </div>
                </div>
                {confirmingId === snap.snapshot_id ? (
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      disabled={restoring}
                      onClick={() => void handleRestore(snap.snapshot_id)}
                      className="px-2 py-1 rounded bg-primary text-text-inverse text-xs hover:bg-primary-hover disabled:opacity-50"
                    >
                      {t('office.snapshot.confirmRestore')}
                    </button>
                    <button
                      type="button"
                      disabled={restoring}
                      onClick={() => setConfirmingId(null)}
                      className="px-2 py-1 rounded border border-border text-xs text-text-secondary hover:bg-bg-hover disabled:opacity-50"
                    >
                      {t('common.cancel')}
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setConfirmingId(snap.snapshot_id)}
                    className="px-2 py-1 rounded border border-border text-xs text-text-secondary hover:bg-bg-hover transition-colors"
                  >
                    {t('office.snapshot.restoreTo')}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
