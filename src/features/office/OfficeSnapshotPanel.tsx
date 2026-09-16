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

import { GitCompare, History, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { officeApi } from '../../shared/api/officeApi';
import type {
  OfficeDocumentSummary,
  OfficeSnapshotMeta,
  OfficeUpdatePreviewResult,
} from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';

import { DiffChangeRow } from './OfficeEditPreviewDialog';

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
  // Round B P2: 与当前版本对比 — which snapshot's diff is expanded
  // (null = collapsed) plus its loaded result / in-flight flag.
  const [diffId, setDiffId] = useState<string | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffResult, setDiffResult] = useState<OfficeUpdatePreviewResult | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setConfirmingId(null);
    setDiffId(null);
    setDiffResult(null);
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
      // 恢复改变了当前文件字节 — 任何展开的 diff 均已过期。
      setDiffId(null);
      setDiffResult(null);
      await onRestored(doc.id);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.snapshot.restoreFailed')}: ${msg}`);
    } finally {
      setRestoring(false);
    }
  };

  const handleToggleDiff = async (snapshotId: string) => {
    if (diffLoading) return;
    if (diffId === snapshotId) {
      setDiffId(null);
      setDiffResult(null);
      return;
    }
    setDiffId(snapshotId);
    setDiffResult(null);
    setDiffLoading(true);
    try {
      const res = await officeApi.diffSnapshot(doc.id, snapshotId);
      setDiffResult(res);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.snapshot.diffFailed')}: ${msg}`);
      setDiffId(null);
    } finally {
      setDiffLoading(false);
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
                className="p-2 border border-border rounded"
              >
                <div className="flex items-center gap-3">
                <div className="flex-1 min-w-0 text-xs text-muted">
                  <div className="text-text text-sm truncate">{snap.snapshot_id}</div>
                  <div className="flex items-center gap-2">
                    <span>{new Date(snap.created_at).toLocaleString()}</span>
                    <span>·</span>
                    <span>{(snap.size_bytes / 1024).toFixed(1)} KB</span>
                  </div>
                </div>
                {/* Round B P2: 与当前版本对比（红绿差异清单，可折叠） */}
                <button
                  type="button"
                  disabled={diffLoading && diffId === snap.snapshot_id}
                  onClick={() => void handleToggleDiff(snap.snapshot_id)}
                  data-testid="office-snapshot-diff-button"
                  aria-expanded={diffId === snap.snapshot_id}
                  className={`flex items-center gap-1 px-2 py-1 rounded border text-xs transition-colors disabled:opacity-50 ${
                    diffId === snap.snapshot_id
                      ? 'border-primary text-primary bg-primary/10'
                      : 'border-border text-text-secondary hover:bg-bg-hover'
                  }`}
                >
                  <GitCompare className="w-3.5 h-3.5" aria-hidden />
                  {t('office.snapshot.diff')}
                </button>
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
                </div>

                {/* 展开的 diff 区块（快照=before，当前=after） */}
                {diffId === snap.snapshot_id && (
                  <div className="mt-2 border-t border-border pt-2" data-testid="office-snapshot-diff">
                    {diffLoading && (
                      <div className="text-xs text-muted text-center py-2">
                        {t('common.loading')}
                      </div>
                    )}
                    {!diffLoading && diffResult && !diffResult.ok && (
                      <div className="text-xs text-error">
                        {t('office.snapshot.diffFailed')}: {diffResult.error ?? ''}
                      </div>
                    )}
                    {!diffLoading && diffResult?.ok && (
                      <>
                        {diffResult.truncated && (
                          <p className="text-xs text-warning mb-2">
                            {t('office.snapshot.diffTruncated')}
                          </p>
                        )}
                        {diffResult.changes.length === 0 ? (
                          <p className="text-xs text-muted">{t('office.snapshot.diffIdentical')}</p>
                        ) : (
                          <ul className="space-y-2">
                            {diffResult.changes.map((change, i) => (
                              <DiffChangeRow key={i} change={change} />
                            ))}
                          </ul>
                        )}
                      </>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
