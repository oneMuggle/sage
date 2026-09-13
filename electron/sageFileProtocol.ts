/**
 * sage-file:// 协议注册 — P9 (UI 优化循环, 2026-09-14)。
 *
 * Electron 21 的 protocol.handle 尚未引入，使用 registerFileProtocol
 * （Electron 22-28 仍可用，win7 线同版本 cherry-pick 安全）。
 * 校验逻辑全部在 ./sageFileUrl（纯函数，可单测）；本模块只做薄注册。
 */
import { protocol } from 'electron';

import { resolveSageFileUrl } from './sageFileUrl';
import { logger } from './logger';

export function registerSageFileProtocol(): void {
  protocol.registerFileProtocol('sage-file', (request, callback) => {
    const resolved = resolveSageFileUrl(request.url);
    if (resolved.ok) {
      callback({ path: resolved.path });
    } else {
      logger.warn('sage-file: rejected', { url: request.url, reason: resolved.reason });
      callback({ error: -3 }); // net::ERR_ABORTED
    }
  });
}
