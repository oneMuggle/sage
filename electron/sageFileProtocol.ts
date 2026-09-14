/**
 * sage-file:// 协议注册 — P9/P13 (UI 优化循环, 2026-09-14)。
 *
 * Electron 21 的 protocol.handle 尚未引入，使用 registerFileProtocol
 * （Electron 22-28 仍可用，win7 线同版本 cherry-pick 安全）。
 * 校验逻辑全部在 ./sageFileUrl（纯函数，可单测）；本模块维护工作区
 * 注册表并做薄注册。
 *
 * P13 收紧：注册表由 main 进程维护，渲染端 SessionWorkspaceProvider
 * 绑定工作区时经 sage-file:register-root IPC 登记。未注册根的文件
 * 一律拒绝（fail-closed），不再信任渲染端 URL 中的 ?ws= 自声明。
 */
import { realpathSync } from 'node:fs';

import { resolveSageFileUrl } from './sageFileUrl';
import { logger } from './logger';

/** 已注册的工作区根（realpath 归一）。 */
const workspaceRoots = new Set<string>();

/**
 * 登记允许 sage-file:// 读取的工作区根。
 * realpath 归一（符号链接/大小写吸收），登记幂等。
 * 返回 true 表示登记成功；false 表示路径无效或不存在。
 */
export function registerWorkspaceRoot(root: string): boolean {
  try {
    const real = realpathSync.native(root);
    workspaceRoots.add(real);
    return true;
  } catch {
    return false;
  }
}

export function registerSageFileProtocol(): void {
  // 动态引入 electron：本模块被 main.ts 静态导入，而若干 electron 单测
  // 会以部分 mock 替换 'electron' —— 顶层静态引入会让这些测试在收集期
  // 因 mock 缺 protocol 导出而报未处理错误。
  void (async () => {
    const { protocol } = await import('electron');
    protocol.registerFileProtocol('sage-file', (request, callback) => {
      const resolved = resolveSageFileUrl(request.url, workspaceRoots);
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
