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

    // 尝试解析 JSON（无论 HTTP 状态）—— 后端在 4xx/5xx 时返回 {error_code, error}
    let json: { media_ref?: unknown; api_url?: string; error?: string; error_code?: string };
    try {
      json = (await resp.json()) as typeof json;
    } catch {
      // JSON 解析失败 —— 回退到原始文本错误
      if (!resp.ok) {
        const text = await resp.text().catch(() => '');
        logger.error('media:upload-attachment failed', { status: resp.status, text });
        throw new Error(`Upload failed: HTTP ${resp.status} — ${text}`);
      }
      throw new Error('Upload failed: invalid JSON response');
    }

    // 向后兼容：如果后端仍返回 HTTP 200 + {error}，视为失败
    if (json && typeof json.error === 'string') {
      logger.error('media:upload-attachment backend error', {
        status: resp.status,
        error_code: json.error_code,
        error: json.error,
      });
      throw new Error(json.error);
    }

    if (!resp.ok) {
      logger.error('media:upload-attachment failed', { status: resp.status });
      throw new Error(`Upload failed: HTTP ${resp.status}`);
    }

    logger.info('media:upload-attachment success', { api_url: json.api_url });
    return { media_ref: json.media_ref, api_url: json.api_url ?? '' };
  }) as (...args: unknown[]) => unknown);
}
