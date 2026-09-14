/**
 * sage-file:// 协议注册 — P9 (UI 优化循环, 2026-09-14)。
 *
 * Electron 21 的 protocol.handle 尚未引入，使用 registerFileProtocol
 * （Electron 22-28 仍可用，win7 线同版本 cherry-pick 安全）。
 * 校验逻辑全部在 ./sageFileUrl（纯函数，可单测）；本模块只做薄注册。
 */
import { resolveSageFileUrl } from './sageFileUrl';
import { logger } from './logger';

export function registerSageFileProtocol(): void {
  // 动态引入 electron：本模块被 main.ts 静态导入，而若干 electron 单测
  // 会以部分 mock 替换 'electron' —— 顶层静态引入会让这些测试在收集期
  // 因 mock 缺 protocol 导出而报未处理错误。
  void (async () => {
    const { protocol } = await import('electron');
    protocol.registerFileProtocol('sage-file', (request, callback) => {
      const resolved = resolveSageFileUrl(request.url);
      if (resolved.ok) {
        callback({ path: resolved.path });
      } else {
        logger.warn('sage-file: rejected', { url: request.url, reason: resolved.reason });
        callback({ error: -3 }); // net::ERR_ABORTED
      }
    });
  })().catch((err: unknown) => {
    logger.warn('sage-file: register failed', { error: String(err) });
  });
}
