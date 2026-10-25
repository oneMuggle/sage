/**
 * Media IPC handler — multipart file upload for chat attachments.
 *
 * Single channel:
 *   media:upload-attachment → multipart POST to /api/v1/chat/attachments
 *
 * Design notes:
 *   - Pure module (no top-level side effects).
 *   - Renderer sends ArrayBuffer + metadata; main process constructs
 *     FormData and POSTs to backend (invokeBackend is JSON-only).
 *   - Follows officeIpc.ts pattern: register function injected by main.ts.
 */

import fetch from 'node-fetch';
import { FormData, Blob } from 'formdata-node';

import { logger } from './logger';

/**
 * Register signature: same shape as Electron's `ipcMain.handle`.
 */
export type RegisterIpcHandler = (
  channel: string,
  handler: (...args: unknown[]) => unknown,
) => void;

/**
 * Register media IPC handlers.
 *
 * @param register - IPC registration function (ipcMain.handle in prod, stub in tests)
 * @param getBackendUrl - Returns backend base URL (e.g., 'http://127.0.0.1:8765')
 * @param getAuthToken - Returns auth token for backend requests
 */
export function registerMediaIpc(
  register: RegisterIpcHandler,
  getBackendUrl: () => string,
  getAuthToken: () => string | undefined,
): void {
  // ── media:upload-attachment ─────────────────────────────────────────────
  // Multipart upload for chat attachments (audio files for ASR, etc.).
  // Renderer sends ArrayBuffer; we construct FormData and POST to backend.
  register('media:upload-attachment', (async (
    _event: unknown,
    payload: { buffer: ArrayBuffer; filename: string; contentType: string },
  ): Promise<{ media_ref: unknown; api_url: string }> => {
    const backendUrl = getBackendUrl();
    const authToken = getAuthToken();

    if (!payload || !payload.buffer || !payload.filename) {
      throw new Error('media:upload-attachment: missing required payload fields');
    }

    // Construct FormData with the file buffer
    const formData = new FormData();
    const blob = new Blob([payload.buffer], {
      type: payload.contentType || 'application/octet-stream',
    });
    formData.append('file', blob, payload.filename);

    // Build headers (auth token if available)
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['X-Sage-Local-Authorization'] = `Bearer ${authToken}`;
    }
    // Don't set Content-Type — let FormData set multipart boundary

    const url = `${backendUrl}/api/v1/chat/attachments`;
    logger.info('media:upload-attachment', {
      url,
      filename: payload.filename,
      size: payload.buffer.byteLength,
    });

    const resp = await fetch(url, {
      method: 'POST',
      headers,
      body: formData as unknown as import('node-fetch').BodyInit,
    });

    if (!resp.ok) {
      const text = await resp.text();
      logger.error('media:upload-attachment failed', { status: resp.status, text });
      throw new Error(`Upload failed: HTTP ${resp.status} — ${text}`);
    }

    const json = (await resp.json()) as { media_ref: unknown; api_url: string };
    logger.info('media:upload-attachment success', { api_url: json.api_url });
    return json;
  }) as (...args: unknown[]) => unknown);
}
