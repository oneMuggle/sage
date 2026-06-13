/**
 * Electron preload script — bridges main ↔ renderer with contextIsolation.
 *
 * Exposes `window.electronAPI` to the React frontend via contextBridge,
 * matching the shape frontend code expects from Tauri (invoke + listen).
 *
 * Phase 1 (2026-06-13):
 *   - invoke(cmd, args) → ipcRenderer.invoke('sage:invoke', { cmd, args })
 *   - listen(event, handler) → ipcRenderer.invoke('sage:listen', { event })
 *                              (Phase 2 will replace with proper on/off relay)
 *
 * Security:
 *   - contextIsolation: true  (this preload runs in isolated world)
 *   - nodeIntegration: false  (renderer is plain web page)
 *   - sandbox: false          (Phase 3 Win7 tradeoff; SUID sandbox helper
 *                              unavailable on Win7 without UAC workaround)
 */
import { contextBridge, ipcRenderer, IpcRendererEvent } from 'electron';

/** UnlistenFn signature mirrors Tauri 2.x for drop-in Phase 2 compatibility. */
export type UnlistenFn = () => void;

const electronAPI = {
  /**
   * Frontend invoke shim — matches `@tauri-apps/api/core` invoke<T>() signature.
   * Phase 2 will replace this entirely; for now it routes through main process.
   */
  invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
    return ipcRenderer.invoke('sage:invoke', { cmd, args: args ?? {} }) as Promise<T>;
  },

  /**
   * Frontend listen shim — matches `@tauri-apps/api/event` listen<T>() signature.
   *
   * Phase 1 stub: just registers a no-op handler that logs. Phase 2 will:
   *   1. call ipcRenderer.invoke('sage:listen', { event }) to subscribe
   *   2. receive payloads via ipcRenderer.on(`sage:event:${event}`, (_e, payload) => handler(payload))
   *   3. return a real UnlistenFn via ipcRenderer.off(...)
   */
  listen<T>(event: string, handler: (payload: T) => void): Promise<UnlistenFn> {
    console.log(`[preload] listen() Phase 1 stub: ${event}`);
    // Forward subscription request to main; main may push events later via webContents.send()
    ipcRenderer.invoke('sage:listen', { event }).catch((e) => console.error('[preload] listen failed:', e));
    // Local listener so renderer can test the IPC pipe (Phase 2 wiring)
    const wrapped = (_e: IpcRendererEvent, payload: T) => handler(payload);
    ipcRenderer.on(`sage:event:${event}`, wrapped);
    const unlisten: UnlistenFn = () => {
      ipcRenderer.off(`sage:event:${event}`, wrapped);
    };
    return Promise.resolve(unlisten);
  },
};

contextBridge.exposeInMainWorld('electronAPI', electronAPI);

// Type augmentation for the renderer side (auto-imported by src/lib/electronApi.d.ts)
export type ElectronAPI = typeof electronAPI;