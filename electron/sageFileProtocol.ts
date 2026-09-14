/**
 * sage-file:// 协议注册 — P9 (UI 优化循环, 2026-09-14)。
 *
 * Electron 44: registerFileProtocol 自 25 起废弃并已移除，改用
 * protocol.handle（Request/Response 语义）。
 *
 * 与旧实现的行为等价性：
 *   - 命中 → 读取 realpath 归一后的绝对路径并以 200 返回；
 *   - 拒绝 → 旧版 callback({ error: -3 }) = net::ERR_ABORTED，新版以 400
 *     响应表达同一「拒绝且不回退」语义（fail-closed 不变）。
 *   - Content-Type 由扩展名显式给出：file:// 响应对 svg/ico 的推断不稳定。
 *
 * 注: win7 线仍在 Electron 21, 该分支须保留 registerFileProtocol 版本,
 * 本文件不可直接 cherry-pick 到 release/win7。
 * 校验逻辑全部在 ./sageFileUrl（纯函数，可单测）；本模块只做薄注册。
 */
import { resolveSageFileUrl } from './sageFileUrl';
import { logger } from './logger';

/** 图片扩展名 → MIME（与 sageFileUrl 的 IMAGE_EXTENSIONS 白名单一一对应）。 */
const MIME_BY_EXT: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.bmp': 'image/bmp',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
};

function mimeFor(filePath: string): string {
  const ext = filePath.slice(filePath.lastIndexOf('.')).toLowerCase();
  return MIME_BY_EXT[ext] ?? 'application/octet-stream';
}

export function registerSageFileProtocol(): void {
  // 动态引入 electron：本模块被 main.ts 静态导入，而若干 electron 单测
  // 会以部分 mock 替换 'electron' —— 顶层静态引入会让这些测试在收集期
  // 因 mock 缺 protocol 导出而报未处理错误。
  void (async () => {
    const { protocol, net } = await import('electron');
    const { pathToFileURL } = await import('node:url');
    protocol.handle('sage-file', async (request) => {
      const resolved = resolveSageFileUrl(request.url);
      if (!resolved.ok) {
        logger.warn('sage-file: rejected', { url: request.url, reason: resolved.reason });
        return new Response(null, { status: 400 });
      }
      // net.fetch + pathToFileURL：由 Electron 读盘，保持流式与 Range 支持。
      const res = await net.fetch(pathToFileURL(resolved.path).toString());
      const headers = new Headers(res.headers);
      headers.set('Content-Type', mimeFor(resolved.path));
      return new Response(res.body, { status: res.status, headers });
    });
  })().catch((err: unknown) => {
    logger.warn('sage-file: register failed', { error: String(err) });
  });
}
