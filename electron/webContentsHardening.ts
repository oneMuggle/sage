/**
 * 全局 webContents 安全加固（2026-09-30）。
 *
 * 背景：2026-09-29 GitHub 发布了 4 条 Electron 高危公告
 * （GHSA-9qh4-3jw8-366w / GHSA-gr2m-v5gq-v685 / GHSA-hq2x-r82h-9wj4 /
 * GHSA-j84w-jfhq-vhvj），修复只出现在 41.10.6+ / 42.9.2+ / 43.4.1+ 版本里。
 * Sage 为了支持 Win7 LTS 固定在 electron@21.4.4（Electron 23 起不再支持 Win7），
 * 无法靠升级修复，因此在应用层收窄攻击面：
 *
 * - 9qh4（<webview> 可在 Web Worker 中开启 Node）：Sage 不使用 <webview>，
 *   所以对所有 webContents 一律拒绝 will-attach-webview。
 * - gr2m / hq2x（从沙箱文档或 iframe 打开的弹窗会丢失 HTML sandbox 限制）：
 *   默认拒绝一切弹窗，http(s) 链接交给系统浏览器打开。窗口自己设置的
 *   setWindowOpenHandler（比如主窗口）会覆盖这里的默认值，行为一致。
 *   不加载本地特权内容的远程登录分区（arena token）允许弹窗，
 *   但强制使用 sandbox / contextIsolation / 无 Node / 无 preload。
 * - j84w（file/HTTP 协议处理器允许跨源读取）：sage-file 协议已有
 *   workspace 与 allowed_paths 白名单（见 sageFileProtocol.ts），
 *   并且没有注册为 privileged scheme，这里不需要额外处理。
 */

import { logger } from './logger';

export interface WindowOpenDetailsLike {
  url: string;
}

export type WindowOpenResult =
  | { action: 'deny' }
  | {
      action: 'allow';
      overrideBrowserWindowOptions: {
        webPreferences: {
          sandbox: true;
          contextIsolation: true;
          nodeIntegration: false;
          nodeIntegrationInSubFrames: false;
          webviewTag: false;
          preload: undefined;
        };
      };
    };

export interface WebContentsLike {
  on(event: 'will-attach-webview', listener: (event: { preventDefault(): void }) => void): unknown;
  setWindowOpenHandler(handler: (details: WindowOpenDetailsLike) => WindowOpenResult): void;
  session?: unknown;
}

export interface AppLike {
  on(event: 'web-contents-created', listener: (event: unknown, contents: WebContentsLike) => void): unknown;
}

export interface HardeningDeps {
  openExternal: (url: string) => void;
  /** 返回 true 表示该 webContents 属于允许（受限）弹窗的远程登录分区。 */
  allowsSandboxedPopups?: (contents: WebContentsLike) => boolean;
  warn?: (message: string, detail?: Record<string, unknown>) => void;
}

export const SANDBOXED_POPUP: WindowOpenResult = {
  action: 'allow',
  overrideBrowserWindowOptions: {
    webPreferences: {
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      nodeIntegrationInSubFrames: false,
      webviewTag: false,
      preload: undefined,
    },
  },
};

export function hardenWebContents(contents: WebContentsLike, deps: HardeningDeps): void {
  contents.on('will-attach-webview', (event) => {
    event.preventDefault();
    deps.warn?.('security: blocked <webview> attach');
  });

  const popupsAllowed = deps.allowsSandboxedPopups?.(contents) ?? false;
  contents.setWindowOpenHandler(({ url }) => {
    if (popupsAllowed && /^https?:\/\//i.test(url)) return SANDBOXED_POPUP;
    deps.openExternal(url);
    return { action: 'deny' };
  });
}

export function installWebContentsHardening(app: AppLike, deps: HardeningDeps): void {
  app.on('web-contents-created', (_event, contents) => {
    try {
      hardenWebContents(contents, deps);
    } catch (err) {
      deps.warn?.('security: hardenWebContents failed', { err: String(err) });
    }
  });
}

/** arena token 登录窗口使用的远程分区（与 arenaTokenWindow.ts 保持一致）。 */
export const ARENA_TOKEN_PARTITION = 'persist:arena-token';

/**
 * main.ts 的接入点。动态引入 electron，原因同 sageFileProtocol.ts：
 * 部分 electron 单测会用不完整的 mock 替换 'electron'。
 * 这里在模块加载时调用，dynamic import 会在 app ready、窗口创建之前完成。
 */
export function installDefaultWebContentsHardening(openExternal: (url: string) => void): void {
  void import('electron')
    .then(({ app, session }) => {
      if (!app?.on || !session?.fromPartition) return;
      installWebContentsHardening(app as unknown as AppLike, {
        openExternal,
        allowsSandboxedPopups: (contents) =>
          contents.session === session.fromPartition(ARENA_TOKEN_PARTITION),
        warn: (message, detail) => logger.warn(message, detail),
      });
    })
    .catch((err: unknown) => {
      logger.warn('security: webContents hardening install failed', { err: String(err) });
    });
}
