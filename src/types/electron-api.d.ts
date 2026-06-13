/**
 * Window.electronAPI type augmentation for renderer code.
 *
 * Phase 1 (2026-06-13): stub type; Phase 2 will tighten with proper
 * invoke command names + listen event payloads once Phase 2 IPC mapping
 * is in place.
 */

export type UnlistenFn = () => void;

export interface ElectronAPI {
  invoke<T = unknown>(cmd: string, args?: Record<string, unknown>): Promise<T>;
  listen<T = unknown>(event: string, handler: (payload: T) => void): Promise<UnlistenFn>;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}

export {};