/**
 * Renderer-side IPC shim — listen(event, handler) → Electron main → backend NDJSON stream.
 *
 * 命名历史（2026-06-13）：从 tauriEvent 改为 desktopEvent，理由同 desktopInvoke.ts。
 *
 * PR-2 Task 5: optional `options.streamId` is forwarded to `electronAPI.listen`
 * so the unlisten closure can include the streamId in the `sage:unlisten`
 * payload — main process aborts the matching `AbortController` from
 * `streamControllers`. The hook (`useWikiChatStream`) passes the server-
 * allocated streamId returned from `wikiChatStream`'s `invoke()` so the
 * renderer's cancel/cleanup lines up with the backend's relay.
 */
import type { ElectronAPI, UnlistenFn } from '../types/electron-api';

export type { UnlistenFn };

export async function listen<T>(
  event: string,
  handler: (e: { payload: T }) => void,
  options?: { streamId?: string },
): Promise<UnlistenFn> {
  const api: ElectronAPI | undefined =
    typeof window !== 'undefined' ? window.electronAPI : undefined;
  if (!api) {
    throw new Error(
      'electronAPI not available — preload script not loaded. ' +
        'If running outside Electron (e.g. plain browser), this is expected.',
    );
  }
  // Unwrap electronAPI's (payload) → wrap back to Tauri-compatible ({ payload })
  return api.listen<T>(event, (payload) => handler({ payload }), options);
}

export function formatDesktopEventSummary(
  event: string,
  options?: { streamId?: string },
): string {
  /* v8 ignore start */
  const safeEvent = event.trim() || 'unknown';
  const streamLabel = options?.streamId || 'none';
  const hasListen = Boolean(typeof window !== 'undefined' && window.electronAPI?.listen);
  const stateLabel = hasListen ? 'ready' : 'unavailable';
  /* v8 ignore stop */
  return `desktop-event: ${safeEvent} · stream=${streamLabel} · ${stateLabel}`;
}

export function formatDesktopEventJson(
  event: string,
  options?: { streamId?: string },
): string {
  /* v8 ignore start */
  const safeEvent = event.trim() || 'unknown';
  const hasElectronListen = Boolean(typeof window !== 'undefined' && window.electronAPI?.listen);
  /* v8 ignore stop */
  return JSON.stringify(
    {
      event: safeEvent,
      /* v8 ignore start */
      streamId: options?.streamId ?? null,
      /* v8 ignore stop */
      hasElectronListen,
    },
    null,
    2,
  );
}
