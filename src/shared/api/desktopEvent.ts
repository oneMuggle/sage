/**
 * Renderer-side IPC shim — listen(event, handler) → Electron main → backend NDJSON stream.
 *
 * 命名历史（2026-06-13）：从 tauriEvent 改为 desktopEvent，理由同 desktopInvoke.ts。
 */
import type { ElectronAPI, UnlistenFn } from '../types/electron-api';

export type { UnlistenFn };

export async function listen<T>(
  event: string,
  handler: (e: { payload: T }) => void,
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
  return api.listen<T>(event, (payload) => handler({ payload }));
}
