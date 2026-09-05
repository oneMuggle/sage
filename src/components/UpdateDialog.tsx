import { useCallback, useEffect, useRef, useState } from 'react';

import type { UpdateState } from '../../electron/updateState';
import { useI18n } from '../shared/lib/i18n';

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === 'string') return error;
  return String(error);
}

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
 *
 * "Defer" records the current version; the dialog only reappears when a
 * different (newer) version is discovered.
 */
export function UpdateDialog() {
  const { t } = useI18n();
  const [state, setState] = useState<UpdateState | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [canRollback, setCanRollback] = useState<{ allowed: boolean; reason?: string }>({
    allowed: false,
  });
  const [dismissedVersion, setDismissedVersion] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isInFlight, setIsInFlight] = useState(false);

  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const mountedRef = useRef(true);

  // ── Focus management (M1) ──────────────────────────────────────────────
  useEffect(() => {
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    // Defer until the dialog is actually rendered
    const frame = requestAnimationFrame(() => {
      const firstButton = dialogRef.current?.querySelector<HTMLElement>('button');
      firstButton?.focus();
    });
    return () => {
      cancelAnimationFrame(frame);
      previousFocusRef.current?.focus?.();
    };
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const safeSetError = useCallback((message: string) => {
    if (!mountedRef.current) return;
    setError(message);
  }, []);

  const safeSetInFlight = useCallback((value: boolean) => {
    if (!mountedRef.current) return;
    setIsInFlight(value);
  }, []);

  useEffect(() => {
    const unlisten =
      window.electronAPI?.updates.onStateChanged((event) => {
        if (event.type === 'state') {
          setState(event.state);
          // Download complete → clear progress bar and in-flight flag
          if (event.state.pendingUpdate) {
            setProgress(null);
            setIsInFlight(false);
          }
        } else if (event.type === 'progress') {
          setProgress(event.percent);
        }
      }) ?? (() => undefined);

    void window.electronAPI?.updates
      .canRollback()
      .then((result) => {
        if (mountedRef.current) setCanRollback(result);
      })
      .catch(() => {
        /* ignore — rollback button stays disabled */
      });

    return unlisten;
  }, []);

  // ── Helpers ────────────────────────────────────────────────────────────
  const runWithGuard = useCallback(
    async (operation: () => Promise<unknown>) => {
      if (isInFlight) return;
      setError(null);
      safeSetInFlight(true);
      try {
        await operation();
      } catch (err: unknown) {
        safeSetError(
          t('updateDialog.operationFailed').replace('{message}', getErrorMessage(err)),
        );
      } finally {
        safeSetInFlight(false);
      }
    },
    [isInFlight, safeSetError, safeSetInFlight, t],
  );

  const handleDownload = useCallback(() => {
    void runWithGuard(() => window.electronAPI!.updates.download());
  }, [runWithGuard]);

  const handleInstall = useCallback(() => {
    void runWithGuard(() => window.electronAPI!.updates.install());
  }, [runWithGuard]);

  const handleDefer = useCallback(() => {
    // Record the version being dismissed so we only reappear for a NEW version.
    const version = state?.pendingUpdate?.version ?? state?.availableUpdate?.version ?? null;
    if (version) setDismissedVersion(version);
  }, [state]);

  const handleRollback = useCallback(() => {
    if (!window.confirm(t('updateDialog.rollbackConfirm'))) return;
    void runWithGuard(() => window.electronAPI!.updates.rollback('manual'));
  }, [runWithGuard, t]);

  // ── Determine visibility ────────────────────────────────────────────────
  const currentDisplayVersion =
    state?.pendingUpdate?.version ?? state?.availableUpdate?.version ?? null;
  const hasPendingUpdate = state?.pendingUpdate != null;
  const isUpdateAvailable = state?.updateAvailable === true;
  const isDownloading = progress !== null && !hasPendingUpdate;
  const isDismissed =
    dismissedVersion != null && currentDisplayVersion != null &&
    dismissedVersion === currentDisplayVersion;

  if (isDismissed) return null;
  if (!hasPendingUpdate && !isUpdateAvailable && !isDownloading) return null;

  // ── Phase 3: Download complete — ready to install ───────────────────────
  if (hasPendingUpdate) {
    const version = state!.pendingUpdate!.version;
    return (
      <DialogShell
        ariaLabel={t('updateDialog.readyToInstall')}
        dialogRef={dialogRef}
        error={error}
      >
        <h3 className="text-sm font-semibold text-text mb-2">{t('updateDialog.readyToInstall')}</h3>
        <p className="text-xs text-text-secondary mb-4">
          {t('updateDialog.readyMessage').replace('{version}', version)}
        </p>
        <DialogFooter
          primaryLabel={t('updateDialog.installNow')}
          onPrimary={handleInstall}
          secondaryLabel={t('updateDialog.restartLater')}
          onSecondary={handleDefer}
          canRollback={canRollback.allowed}
          rollbackLabel={t('updateDialog.rollback')}
          onRollback={handleRollback}
          rollbackDisabled={!canRollback.allowed || isInFlight}
          primaryDisabled={isInFlight}
        />
      </DialogShell>
    );
  }

  // ── Phase 2: Downloading ────────────────────────────────────────────────
  if (isDownloading) {
    const version = state?.availableUpdate?.version ?? state?.currentVersion ?? '';
    const percent = Math.round(progress!);
    return (
      <DialogShell
        ariaLabel={t('updateDialog.downloading').replace('{version}', version)}
        dialogRef={dialogRef}
        error={error}
      >
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
          onRollback={handleRollback}
          rollbackDisabled={!canRollback.allowed || isInFlight}
          primaryDisabled={isInFlight}
        />
      </DialogShell>
    );
  }

  // ── Phase 1: Update available (not yet downloaded) ──────────────────────
  const version = state?.availableUpdate?.version ?? '';
  const releaseNotes = state?.availableUpdate?.releaseNotes;
  return (
    <DialogShell
      ariaLabel={t('updateDialog.newVersion').replace('{version}', version)}
      dialogRef={dialogRef}
      error={error}
    >
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
        onPrimary={handleDownload}
        secondaryLabel={t('updateDialog.later')}
        onSecondary={handleDefer}
        canRollback={canRollback.allowed}
        rollbackLabel={t('updateDialog.rollback')}
        onRollback={handleRollback}
        rollbackDisabled={!canRollback.allowed || isInFlight}
        primaryDisabled={isInFlight}
      />
    </DialogShell>
  );
}

// ── Private sub-components ──────────────────────────────────────────────────

interface DialogShellProps {
  ariaLabel: string;
  children: React.ReactNode;
  dialogRef: React.RefObject<HTMLDivElement>;
  error: string | null;
}

function DialogShell({ ariaLabel, children, dialogRef, error }: DialogShellProps) {
  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      role="presentation"
      data-testid="update-dialog-overlay"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        data-testid="update-dialog"
        className="bg-surface border border-border rounded-lg w-full max-w-[480px] mx-4 p-5 shadow-xl outline-none"
      >
        {error && (
          <div
            role="alert"
            data-testid="update-dialog-error"
            className="mb-3 px-3 py-2 text-xs rounded bg-danger/10 text-danger border border-danger/30"
          >
            {error}
          </div>
        )}
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
  primaryDisabled?: boolean;
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
  primaryDisabled,
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
            disabled={primaryDisabled}
            className="px-3 py-1.5 text-xs bg-primary text-text-inverse rounded hover:bg-primary-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {primaryLabel}
          </button>
        )}
      </div>
    </div>
  );
}
