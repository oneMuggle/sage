/**
 * Window.electronAPI type augmentation for renderer code.
 *
 * Phase 1 (2026-06-13): stub type; Phase 2 will tighten with proper
 * invoke command names + listen event payloads once Phase 2 IPC mapping
 * is in place.
 *
 * Phase 5 (2026-06-25): added windowControls bridge for custom titlebar.
 */

import type { WindowControlsBridge } from '../api/windowControlsClient';

export type UnlistenFn = () => void;

export interface ElectronAPI {
  invoke<T = unknown>(cmd: string, args?: Record<string, unknown>): Promise<T>;
  listen<T = unknown>(event: string, handler: (payload: T) => void): Promise<UnlistenFn>;
  windowControls: WindowControlsBridge;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}

export {};
