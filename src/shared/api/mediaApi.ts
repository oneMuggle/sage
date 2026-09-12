/**
 * Media API helpers — URL resolution and blob fetching for multimodal content.
 */

import { backendRequest } from './backendRequest';

/**
 * Get the backend base URL for direct access (prod mode).
 * In dev mode, Vite proxy handles /api routes.
 */
function getBackendBaseUrl(): string {
  // In Electron prod, use direct backend URL
  if (window.electronAPI) {
    return 'http://127.0.0.1:8765';
  }
  // In dev browser mode, use relative URL (Vite proxy)
  return '';
}

/**
 * Resolve a backend API URL (like /api/v1/media/{id}) to a usable URL.
 * - Dev: returns the URL as-is (Vite proxy handles it)
 * - Prod Electron: returns full backend URL
 */
export function resolveMediaUrl(apiUrl: string): string {
  if (import.meta.env.DEV) {
    // Vite proxy handles /api → :8765
    return apiUrl;
  }
  // Prod: direct backend URL (CORS already allows 127.0.0.1)
  const base = getBackendBaseUrl();
  return `${base}${apiUrl}`;
}

/**
 * Fetch media file as blob URL via Electron IPC.
 * Returns a blob: URL suitable for <img src> and <audio src>.
 * Works in both dev and prod.
 */
export async function fetchMediaBlobUrl(
  mediaId: string,
  mimeType?: string,
): Promise<string> {
  const bridge = window.electronAPI?.backendRequest;
  if (!bridge) {
    throw new Error('electronAPI.backendRequest not available');
  }

  const buffer = await bridge<ArrayBuffer>({
    method: 'GET',
    path: `/api/v1/media/${mediaId}`,
    responseType: 'arraybuffer',
  });

  const blob = new Blob([buffer], mimeType ? { type: mimeType } : {});
  return URL.createObjectURL(blob);
}

/**
 * Revoke a blob URL to free memory.
 * Call this in component cleanup (useEffect return).
 */
export function revokeMediaBlobUrl(blobUrl: string): void {
  if (blobUrl.startsWith('blob:')) {
    URL.revokeObjectURL(blobUrl);
  }
}
