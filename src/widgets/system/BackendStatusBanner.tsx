import { useEffect, useState } from 'react';
import './BackendStatusBanner.css';

type BannerState = 'ok' | 'reconnecting' | 'failed' | 'recovered';

const RECOVERED_VISIBLE_MS = 2000;

export function BackendStatusBanner() {
  const [state, setState] = useState<BannerState>('ok');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let off1: (() => void) | undefined;
    let off2: (() => void) | undefined;
    let recoverTimer: ReturnType<typeof setTimeout> | undefined;

    const setup = async () => {
      const api = window.electronAPI;
      if (!api) {
        // Preload not loaded (web mode or test env without bridge).
        // Banner has nothing to subscribe to; silently no-op.
        return;
      }
      // window.electronAPI.listen returns Promise<UnlistenFn> in production
      // (see electron/preload.ts). Await both before scheduling teardown.
      const [unlisten1, unlisten2] = await Promise.all([
        api.listen('backend:disconnected', (p: { attempt: number }) => {
          setAttempt(p.attempt);
          setState(p.attempt === -1 ? 'failed' : 'reconnecting');
        }),
        api.listen('backend:reconnected', () => {
          setState('recovered');
          if (recoverTimer) clearTimeout(recoverTimer);
          recoverTimer = setTimeout(() => {
            setState('ok');
          }, RECOVERED_VISIBLE_MS);
        }),
      ]);
      if (cancelled) {
        unlisten1();
        unlisten2();
        return;
      }
      off1 = unlisten1;
      off2 = unlisten2;
    };

    setup().catch((err) => {
      // If listen setup fails (e.g. preload not loaded), surface in console
      // without throwing — the app must remain usable.
      // eslint-disable-next-line no-console
      console.error('[BackendStatusBanner] listen setup failed:', err);
    });

    return () => {
      cancelled = true;
      if (recoverTimer) clearTimeout(recoverTimer);
      off1?.();
      off2?.();
    };
  }, []);

  if (state === 'ok') return null;

  const variant = state === 'failed' ? 'error' : state === 'recovered' ? 'success' : 'warning';
  const message =
    state === 'reconnecting'
      ? `后端暂时断开，正在自动重连（第 ${attempt}/3 次）...`
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