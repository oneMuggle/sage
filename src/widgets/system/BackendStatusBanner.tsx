import { useEffect, useState } from 'react';
import './BackendStatusBanner.css';

type BannerState = 'ok' | 'starting' | 'reconnecting' | 'failed' | 'recovered' | 'auth_failed';

const RECOVERED_VISIBLE_MS = 2000;

/**
 * Backend lifecycle banner.
 *
 * Listens to four IPC channels from the Electron main process:
 *   - `backend:starting`  → "starting…" (cold-start race window)
 *   - `backend:ready`      → clear the banner
 *   - `backend:disconnected` → "reconnecting" / "please restart Sage"
 *   - `backend:reconnected` → "recovered" (auto-clears after 2s)
 *
 * Task 0 review round 1, finding #6: the renderer now gets explicit
 * starting/ready events, not just the post-mortem disconnected/reconnected
 * pair, so the banner no longer flashes empty on cold start.
 */
export function BackendStatusBanner() {
  const [state, setState] = useState<BannerState>('ok');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const offs: Array<() => void> = [];
    let recoverTimer: ReturnType<typeof setTimeout> | undefined;

    const setup = async () => {
      const api = window.electronAPI;
      if (!api) {
        // Preload not loaded (web mode or test env without bridge).
        // Banner has nothing to subscribe to; silently no-op.
        return;
      }
      // window.electronAPI.listen returns Promise<UnlistenFn> in production
      // (see electron/preload.ts). Await all before scheduling teardown.
      const [offStarting, offReady, offDisconnected, offReconnected, offAuthFailed] =
        await Promise.all([
          api.listen('backend:starting', () => {
            // Don't overwrite a more severe state (e.g. 'failed' or 'auth_failed') with 'starting'.
            setState((prev) => (prev === 'failed' || prev === 'auth_failed' ? prev : 'starting'));
          }),
          api.listen('backend:ready', () => {
            // Auth mismatch is only cleared by a full app restart (token is process-local
            // and won't change until then). backend:ready in between won't help.
            setState((prev) => (prev === 'auth_failed' ? prev : 'ok'));
          }),
          api.listen('backend:disconnected', (p: { attempt: number }) => {
            setAttempt(p.attempt);
            setState(p.attempt === -1 ? 'failed' : 'reconnecting');
          }),
          api.listen('backend:reconnected', () => {
            setState((prev) => (prev === 'auth_failed' ? prev : 'recovered'));
            if (recoverTimer) clearTimeout(recoverTimer);
            recoverTimer = setTimeout(() => {
              setState((prev) => (prev === 'auth_failed' ? prev : 'ok'));
            }, RECOVERED_VISIBLE_MS);
          }),
          api.listen('backend:auth-failed', (p: { status: number }) => {
            // Probe in main.ts detected token mismatch on startup. Distinct from
            // 'failed' (which means backend itself is unreachable) — here backend
            // is alive but rejects our capability; only restart fixes it.
            console.error(`[BackendStatusBanner] backend auth probe rejected (HTTP ${p.status})`);
            setState('auth_failed');
          }),
        ]);
      if (cancelled) {
        offStarting();
        offReady();
        offDisconnected();
        offReconnected();
        offAuthFailed();
        return;
      }
      offs.push(offStarting, offReady, offDisconnected, offReconnected, offAuthFailed);
    };

    setup().catch((err) => {
      // If listen setup fails (e.g. preload not loaded), surface in console
      // without throwing — the app must remain usable.
      console.error('[BackendStatusBanner] listen setup failed:', err);
    });

    return () => {
      cancelled = true;
      if (recoverTimer) clearTimeout(recoverTimer);
      offs.forEach((fn) => fn());
    };
  }, []);

  if (state === 'ok') return null;

  const variant =
    state === 'auth_failed'
      ? 'error'
      : state === 'failed' || state === 'starting'
        ? 'warning'
        : state === 'recovered'
          ? 'success'
          : 'warning';
  const message =
    state === 'starting'
      ? '后端服务正在启动…'
      : state === 'reconnecting'
        ? `后端暂时断开，正在自动重连（第 ${attempt}/3 次）...`
        : state === 'auth_failed'
          ? '后端授权凭据失效（HTTP 401）。请重启 Sage 桌面端恢复'
          : state === 'failed'
            ? '后端连接失败，请重启 Sage'
            : '已恢复';

  return (
    <div
      role="status"
      data-testid={`backend-banner-${state}`}
      className={`banner banner-${variant}`}
    >
      {message}
    </div>
  );
}
