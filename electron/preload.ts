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
import type { WindowControlsBridge } from '../src/shared/api/windowControlsClient';

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
   * Phase 2 wiring:
   *   1. call ipcRenderer.invoke('sage:listen', { event }) to subscribe in main;
   *      main opens backend NDJSON relay and pushes events via webContents.send
   *   2. receive payloads via ipcRenderer.on(`sage:event:${event}`, (_e, payload) => handler(payload))
   *   3. unlisten() invokes sage:unlisten to abort backend relay + remove listener
   */
  listen<T>(event: string, handler: (payload: T) => void): Promise<UnlistenFn> {
    // Forward subscription request to main; main opens backend relay
    ipcRenderer
      .invoke('sage:listen', { event })
      .catch((e) => console.error(`[preload] listen(${event}) failed:`, e));
    // Local listener so renderer receives relayed events
    const wrapped = (_e: IpcRendererEvent, payload: T) => handler(payload);
    ipcRenderer.on(`sage:event:${event}`, wrapped);
    const unlisten: UnlistenFn = () => {
      ipcRenderer.off(`sage:event:${event}`, wrapped);
      ipcRenderer.invoke('sage:unlisten', { event }).catch(() => undefined);
    };
    return Promise.resolve(unlisten);
  },

  /**
   * Phase 5: Window controls bridge for custom titlebar.
   * Delegates to main process IPC handlers (sage:window-controls:*).
   */
  windowControls: {
    minimize: () => ipcRenderer.invoke('sage:window-controls:minimize'),
    toggleMaximize: () => ipcRenderer.invoke('sage:window-controls:toggle-maximize'),
    close: () => ipcRenderer.invoke('sage:window-controls:close'),
    capturePage: () => ipcRenderer.invoke('sage:window-controls:capture-page') as Promise<string>,
    isMaximized: () => ipcRenderer.invoke('sage:window-controls:is-maximized') as Promise<boolean>,
  } satisfies WindowControlsBridge,
};

contextBridge.exposeInMainWorld('electronAPI', electronAPI);

// Type augmentation for the renderer side (auto-imported by src/lib/electronApi.d.ts)
export type ElectronAPI = typeof electronAPI;
