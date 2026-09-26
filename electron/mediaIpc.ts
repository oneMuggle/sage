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

import { randomBytes } from 'node:crypto';

import fetch from 'node-fetch';

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

    // node-fetch 2 does not serialize WHATWG FormData. Encode exact bytes;
    // no ReadableStream/global fetch APIs absent in Electron 21 are required.
    if (typeof payload.filename !== 'string' || /[\r\n\0]/.test(payload.filename)) {
      throw new Error('Invalid attachment filename');
    }
    const filename = payload.filename.replace(/\\/g, '%5C').replace(/"/g, '%22');
    const contentType = payload.contentType || 'application/octet-stream';
    if (typeof contentType !== 'string' || !/^[a-zA-Z0-9!#$&^_.+-]+\/[a-zA-Z0-9!#$&^_.+-]+(?:;[ \t\x21-\x7e]*)?$/.test(contentType)) {
      throw new Error('Invalid attachment content type');
    }
    const boundary = 'sage-' + randomBytes(24).toString('hex');
    const body = Buffer.concat([
      Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${filename}"\r\nContent-Type: ${contentType}\r\n\r\n`, 'utf8'),
      Buffer.from(payload.buffer),
      Buffer.from(`\r\n--${boundary}--\r\n`),
    ]);

    // Build headers (auth token if available)
    const headers: Record<string, string> = { 'Content-Type': `multipart/form-data; boundary=${boundary}`, 'Content-Length': String(body.length) };
    if (authToken) {
      headers['X-Sage-Local-Authorization'] = `Bearer ${authToken}`;
    }
    // Boundary and Content-Length correspond to the actual Buffer body.

    const url = `${backendUrl}/api/v1/chat/attachments`;
    logger.info('media:upload-attachment', {
      url,
      filename: payload.filename,
      size: payload.buffer.byteLength,
    });

    const resp = await fetch(url, {
      method: 'POST',
      headers,
      body,
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
