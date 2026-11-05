/**
 * sage-preview:// protocol —— 给 HTML 预览提供独立源（origin）。
 *
 * 为什么需要独立源：预览页此前用 srcdoc 内联在渲染层 iframe 里。srcdoc
 * 文档**继承父文档的 CSP**，而生产构建注入的 CSP 是
 * `script-src 'self' file: <hash>`（无 'unsafe-inline'、无 https:）——
 * 于是预览页里的内联脚本与 CDN 脚本在打包版全部被拦截，HTML 预览在生产
 * 环境下只剩静态排版。独立源让预览文档拥有自己的 CSP 上下文（不受渲染层
 * CSP 约束），预览页里的脚本按预期运行。
 *
 * 安全边界：
 * - 文档由渲染层经 IPC 投递（内容即用户自己的产物/代码块），主进程不读盘。
 * - 预览 iframe 仍是 `sandbox="allow-scripts"`（无 allow-same-origin），
 *   文档实际运行在 opaque origin，拿不到应用 cookie / storage / DOM。
 * - 注册表只保留最近若干份内容，超出即淘汰最早的，避免长期运行内存膨胀。
 */
import { randomUUID } from 'node:crypto';

import { logger } from './logger';

export const PREVIEW_SCHEME = 'sage-preview';

/** 注册表上限 —— 超出后淘汰最早发布的内容。 */
const MAX_PREVIEWS = 32;

/** id → html 原文。按插入顺序淘汰。 */
const previewRegistry = new Map<string, string>();

export interface PreviewPublishResult {
  id: string;
  url: string;
}

/**
 * 注册签名：与 Electron 的 `ipcMain.handle` 同形。
 * 生产调用方传 `(channel, handler) => ipcMain.handle(channel, handler)`，
 * 测试注入 Map 桩。
 */
export type RegisterIpcHandler = (
  channel: string,
  handler: (...args: unknown[]) => unknown,
) => void;

export function publishPreview(html: string): PreviewPublishResult {
  const id = randomUUID();
  previewRegistry.set(id, html);
  while (previewRegistry.size > MAX_PREVIEWS) {
    const oldest = previewRegistry.keys().next();
    if (oldest.done) break;
    previewRegistry.delete(oldest.value);
  }
  return { id, url: `${PREVIEW_SCHEME}://${id}/index.html` };
}

export function revokePreview(id: string): void {
  previewRegistry.delete(id);
}

export function getPreviewHtml(id: string): string | undefined {
  return previewRegistry.get(id);
}

export function clearPreviews(): void {
  previewRegistry.clear();
}

/**
 * 解析 `sage-preview://<id>/<path>`。
 * 返回 null 表示协议不符或 id 缺失（非本协议请求不应被本处理器应答）。
 */
export function parsePreviewUrl(url: string): { id: string; path: string } | null {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.protocol !== `${PREVIEW_SCHEME}:`) return null;
  const id = parsed.hostname;
  if (!id) return null;
  return { id, path: parsed.pathname || '/' };
}

let schemeRegistered = false;

/**
 * 必须在 `app.whenReady()` 之前调用。幂等。
 *
 * 采用与 sage-pet:// 相同的动态 import 写法：模块顶层不 import electron，
 * 这样纯函数（注册表 / URL 解析）可以在 vitest 里直接测。
 */
export function registerPreviewScheme(): void {
  if (schemeRegistered) return;
  schemeRegistered = true;
  void (async () => {
    const { protocol } = await import('electron');
    protocol.registerSchemesAsPrivileged([
      {
        scheme: PREVIEW_SCHEME,
        privileges: {
          standard: true,
          secure: true,
          supportFetchAPI: true,
          corsEnabled: true,
        },
      },
    ]);
  })().catch((error: unknown) => {
    logger.warn('preview: register scheme failed', { error: String(error) });
  });
}

let protocolRegistered = false;

/** 必须在 `app.whenReady()` 之后调用。幂等。 */
export function registerPreviewProtocol(): void {
  if (protocolRegistered) return;
  protocolRegistered = true;
  void (async () => {
    const { protocol } = await import('electron');
    protocol.registerBufferProtocol(PREVIEW_SCHEME, (request, callback) => {
      const method = (request.method || 'GET').toUpperCase();
      if (method !== 'GET' && method !== 'HEAD') {
        callback({ statusCode: 405, headers: { Allow: 'GET, HEAD' } });
        return;
      }
      const parsed = parsePreviewUrl(request.url);
      if (!parsed) {
        callback({ error: -10 }); // net::ERR_ACCESS_DENIED
        return;
      }
      const html = getPreviewHtml(parsed.id);
      if (html === undefined || (parsed.path !== '/' && parsed.path !== '/index.html')) {
        // 只应命中入口文档；其余路径（favicon、相对资源）一律 404。
        callback({
          statusCode: 404,
          headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' },
          data: Buffer.from('<!doctype html><meta charset="utf-8"><p>预览资源不存在</p>', 'utf-8'),
        });
        return;
      }
      callback({
        statusCode: 200,
        headers: {
          'Content-Type': 'text/html; charset=utf-8',
          'Cache-Control': 'no-store',
        },
        data: method === 'HEAD' ? Buffer.alloc(0) : Buffer.from(html, 'utf-8'),
      });
    });
  })().catch((error: unknown) => {
    logger.warn('preview: register protocol failed', { error: String(error) });
  });
}

/**
 * 注册预览 IPC：
 *   preview:publish → { id, url }   渲染层投递 HTML，换取可加载的 URL
 *   preview:revoke  → boolean       渲染层丢弃不再需要的预览
 */
export function registerPreviewIpc(register: RegisterIpcHandler): void {
  register('preview:publish', (_evt: unknown, html: unknown) => {
    const content = typeof html === 'string' ? html : '';
    return publishPreview(content);
  });
  register('preview:revoke', (_evt: unknown, id: unknown) => {
    if (typeof id !== 'string' || !id) return false;
    revokePreview(id);
    return true;
  });
}
