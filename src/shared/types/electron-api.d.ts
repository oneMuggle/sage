/**
 * Window.electronAPI type augmentation for renderer code.
 *
 * Phase 1 (2026-06-13): stub type.
 * Phase 2 (2026-06-28): added theme namespace mirroring preload.ts additions.
 */

import type {
  ActiveTheme,
  ThemePreset,
  ThemeValidationResult,
} from './theme';
import type { ApiResponse } from './api';

export type UnlistenFn = () => void;

export interface ElectronAPITheme {
  list: () => Promise<ApiResponse<ThemePreset[]>>;
  get: (id: string) => Promise<ApiResponse<ThemePreset>>;
  save: (preset: ThemePreset) => Promise<ApiResponse<ThemePreset>>;
  delete: (id: string) => Promise<ApiResponse<{ deleted: string }>>;
  getActive: () => Promise<ApiResponse<ActiveTheme>>;
  saveActive: (active: ActiveTheme) => Promise<ApiResponse<ActiveTheme>>;
  validate: (css: string) => Promise<ApiResponse<ThemeValidationResult>>;
}

export interface ElectronAPI {
  invoke<T = unknown>(cmd: string, args?: Record<string, unknown>): Promise<T>;
  listen<T = unknown>(event: string, handler: (payload: T) => void): Promise<UnlistenFn>;
  theme: ElectronAPITheme;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}

export {};
