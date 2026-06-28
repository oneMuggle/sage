/**
 * Typed wrapper around window.electronAPI.theme.* IPC calls.
 * Returns ApiResponse<T> envelope; never throws.
 *
 * The `theme` field on Window.electronAPI is declared globally in
 * src/shared/types/electron-api.d.ts (Phase 2 wiring).
 */
import type { ApiResponse } from '../types/api';
import type { ActiveTheme, ThemePreset, ThemeValidationResult } from '../types/theme';

const UNAVAILABLE: ApiResponse<never> = {
  success: false,
  error: 'IPC not available: window.electronAPI is undefined',
  code: 'IPC_UNAVAILABLE',
};

function ensureAPI() {
  if (typeof window === 'undefined' || !window.electronAPI?.theme) {
    return null;
  }
  return window.electronAPI.theme;
}

export async function listThemes(): Promise<ApiResponse<ThemePreset[]>> {
  const api = ensureAPI();
  if (!api) return UNAVAILABLE;
  try {
    return await api.list();
  } catch (e) {
    return { success: false, error: String(e), code: 'IPC_EXCEPTION' };
  }
}

export async function getTheme(id: string): Promise<ApiResponse<ThemePreset>> {
  const api = ensureAPI();
  if (!api) return UNAVAILABLE;
  try {
    return await api.get(id);
  } catch (e) {
    return { success: false, error: String(e), code: 'IPC_EXCEPTION' };
  }
}

export async function saveTheme(preset: ThemePreset): Promise<ApiResponse<ThemePreset>> {
  const api = ensureAPI();
  if (!api) return UNAVAILABLE;
  try {
    return await api.save(preset);
  } catch (e) {
    return { success: false, error: String(e), code: 'IPC_EXCEPTION' };
  }
}

export async function deleteTheme(id: string): Promise<ApiResponse<{ deleted: string }>> {
  const api = ensureAPI();
  if (!api) return UNAVAILABLE;
  try {
    return await api.delete(id);
  } catch (e) {
    return { success: false, error: String(e), code: 'IPC_EXCEPTION' };
  }
}

export async function getActiveTheme(): Promise<ApiResponse<ActiveTheme>> {
  const api = ensureAPI();
  if (!api) return UNAVAILABLE;
  try {
    return await api.getActive();
  } catch (e) {
    return { success: false, error: String(e), code: 'IPC_EXCEPTION' };
  }
}

export async function saveActiveTheme(active: ActiveTheme): Promise<ApiResponse<ActiveTheme>> {
  const api = ensureAPI();
  if (!api) return UNAVAILABLE;
  try {
    return await api.saveActive(active);
  } catch (e) {
    return { success: false, error: String(e), code: 'IPC_EXCEPTION' };
  }
}

export async function validateThemeCss(css: string): Promise<ApiResponse<ThemeValidationResult>> {
  const api = ensureAPI();
  if (!api) return UNAVAILABLE;
  try {
    return await api.validate(css);
  } catch (e) {
    return { success: false, error: String(e), code: 'IPC_EXCEPTION' };
  }
}