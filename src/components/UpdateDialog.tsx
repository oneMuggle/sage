import { useCallback, useEffect, useRef, useState } from 'react';

import type { UpdateState } from '../../electron/updateState';
import { useI18n } from '../shared/lib/i18n';

/**
 * UpdateDialog — global modal that notifies the user about available updates.
 *
 * Lifecycle phases:
 *   1. "update available" — state.updateAvailable === true, no pendingUpdate
 *   2. "downloading"      — download progress events are flowing (0–100 %)
 *   3. "ready to install" — state.pendingUpdate is set
 *
 * The dialog is NOT dismissible by backdrop click or ESC — the user must
 * explicitly choose an action (install / download / defer / rollback).
 */
export function UpdateDialog() {
  const { t } = useI18n();
  const [state, setState] = useState<UpdateState | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [canRollback, setCanRollback] = useState<{ allowed: boolean; reason?: string }>({
    allowed: false,
  });
  const [dismissed, setDismissed] = useState(false);
  const previousVersionRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    const unlisten =
      window.electronAPI?.updates.onStateChanged((event) => {
        if (event.type === 'state') {
          setState(event.state);
          // A new update being discovered → un-dismiss so the dialog shows
          if (event.state.updateAvailable && !previousVersionRef.current) {
            setDismissed(false);
          }
          previousVersionRef.current = event.state.pendingUpdate?.version;
          // Download complete → clear progress bar
          if (event.state.pendingUpdate) {
            setProgress(null);
          }
        } else if (event.type === 'progress') {
          setProgress(event.percent);
        }
      }) ?? (() => undefined);

    void window.electronAPI?.updates.canRollback().then(setCanRollback);

    return unlisten;
  }, []);

  const handleDownload = useCallback(() => {
    void window.electronAPI?.updates.download();
  }, []);

  const handleInstall = useCallback(() => {
    void window.electronAPI?.updates.install();
  }, []);

  const handleDefer = useCallback(() => {
    setDismissed(true);
  }, []);

  const handleRollback = useCallback(async () => {
    if (!window.confirm(t('updateDialog.rollbackConfirm'))) return;
    await window.electronAPI?.updates.rollback('manual');
  }, [t]);

  // ── Determine visibility ────────────────────────────────────────────
  const hasPendingUpdate = state?.pendingUpdate != null;
  const isUpdateAvailable = state?.updateAvailable === true;
  const isDownloading = progress !== null && !hasPendingUpdate;

  if (!hasPendingUpdate && !isUpdateAvailable && !isDownloading) return null;
  if (dismissed && !hasPendingUpdate) return null;

  // ── Phase 3: Download complete — ready to install ───────────────────
  if (hasPendingUpdate) {
    const version = state!.pendingUpdate!.version;
    return (
      <DialogShell ariaLabel={t('updateDialog.readyToInstall')}>
        <h3 className="text-sm font-semibold text-text mb-2">{t('updateDialog.readyToInstall')}</h3>
        <p className="text-xs text-text-secondary mb-4">
          {t('updateDialog.readyMessage').replace('{version}', version)}
        </p>
        <DialogFooter
          primaryLabel={t('updateDialog.installNow')}
          onPrimary={() => void handleInstall()}
          secondaryLabel={t('updateDialog.restartLater')}
          onSecondary={handleDefer}
          canRollback={canRollback.allowed}
          rollbackLabel={t('updateDialog.rollback')}
          onRollback={() => void handleRollback()}
          rollbackDisabled={!canRollback.allowed}
        />
      </DialogShell>
    );
  }

  // ── Phase 2: Downloading ───────────────────────────────────────────
  if (isDownloading) {
    const version = state?.availableUpdate?.version ?? state?.currentVersion ?? '';
    const percent = Math.round(progress!);
    return (
      <DialogShell ariaLabel={t('updateDialog.downloading').replace('{version}', version)}>
        <h3 className="text-sm font-semibold text-text mb-2">
          {t('updateDialog.downloading').replace('{version}', version)}
        </h3>
        <div className="mb-4">
          <div className="w-full h-2 bg-border rounded overflow-hidden">
            <div
              className="h-full bg-primary transition-all duration-200"
              style={{ width: `${percent}%` }}
              role="progressbar"
              aria-valuenow={percent}
              aria-valuemin={0}
              aria-valuemax={100}
              data-testid="update-dialog-progress"
            />
          </div>
          <p className="text-xs text-muted mt-1 text-right" data-testid="update-dialog-percent">
            {percent}%
          </p>
        </div>
        <DialogFooter
          secondaryLabel={t('updateDialog.later')}
          onSecondary={handleDefer}
          canRollback={canRollback.allowed}
          rollbackLabel={t('updateDialog.rollback')}
          onRollback={() => void handleRollback()}
          rollbackDisabled={!canRollback.allowed}
        />
      </DialogShell>
    );
  }

  // ── Phase 1: Update available (not yet downloaded) ─────────────────
  const version = state?.availableUpdate?.version ?? '';
  const releaseNotes = state?.availableUpdate?.releaseNotes;
  return (
    <DialogShell ariaLabel={t('updateDialog.newVersion').replace('{version}', version)}>
      <h3 className="text-sm font-semibold text-text mb-2">
        {t('updateDialog.newVersion').replace('{version}', version)}
      </h3>
      <div className="mb-4 max-h-[300px] overflow-y-auto">
        <p className="text-xs text-text-secondary font-medium mb-1">
          {t('updateDialog.releaseNotes')}
        </p>
        {releaseNotes ? (
          <pre className="text-xs text-text-secondary whitespace-pre-wrap break-words font-sans leading-relaxed">
            {releaseNotes}
          </pre>
        ) : (
          <p className="text-xs text-muted italic" data-testid="update-dialog-no-notes">
            {t('updateDialog.noReleaseNotes')}
          </p>
        )}
      </div>
      <DialogFooter
        primaryLabel={t('updateDialog.downloadNow')}
        onPrimary={() => void handleDownload()}
        secondaryLabel={t('updateDialog.later')}
        onSecondary={handleDefer}
        canRollback={canRollback.allowed}
        rollbackLabel={t('updateDialog.rollback')}
        onRollback={() => void handleRollback()}
        rollbackDisabled={!canRollback.allowed}
      />
    </DialogShell>
  );
}

// ── Private sub-components ──────────────────────────────────────────────────

interface DialogShellProps {
  ariaLabel: string;
  children: React.ReactNode;
}

function DialogShell({ ariaLabel, children }: DialogShellProps) {
  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      role="presentation"
      data-testid="update-dialog-overlay"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        data-testid="update-dialog"
        className="bg-surface border border-border rounded-lg w-full max-w-[480px] mx-4 p-5 shadow-xl"
      >
        {children}
      </div>
    </div>
  );
}

interface DialogFooterProps {
  primaryLabel?: string;
  onPrimary?: () => void;
  secondaryLabel: string;
  onSecondary: () => void;
  canRollback: boolean;
  rollbackLabel: string;
  onRollback: () => void;
  rollbackDisabled: boolean;
}

function DialogFooter({
  primaryLabel,
  onPrimary,
  secondaryLabel,
  onSecondary,
  canRollback,
  rollbackLabel,
  onRollback,
  rollbackDisabled,
}: DialogFooterProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
      {canRollback ? (
        <button
          type="button"
          data-testid="update-dialog-rollback"
          onClick={onRollback}
          disabled={rollbackDisabled}
          className="text-xs text-primary underline-offset-2 hover:underline disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {rollbackLabel}
        </button>
      ) : (
        <span />
      )}
      <div className="flex gap-2">
        {secondaryLabel && (
          <button
            type="button"
            data-testid="update-dialog-secondary"
            onClick={onSecondary}
            className="px-3 py-1.5 text-xs border border-border rounded text-text-secondary hover:text-text hover:bg-bg-hover transition-colors"
          >
            {secondaryLabel}
          </button>
        )}
        {primaryLabel && onPrimary && (
          <button
            type="button"
            data-testid="update-dialog-primary"
            onClick={onPrimary}
            className="px-3 py-1.5 text-xs bg-primary text-text-inverse rounded hover:bg-primary-hover transition-colors"
          >
            {primaryLabel}
          </button>
        )}
      </div>
    </div>
  );
}
