/**
 * 内置 Agent 浏览器宿主（P1）：把 Electron BrowserWindow / session 接到
 * `agentBrowserBridge` 的依赖注入接口上。
 *
 * 所有窗口共享 `persist:sage-agent-browser` 分区：登录窗口与 web_fetch 渲染池
 * 使用同一份 cookie + localStorage，登录一次即可跨通道复用。窗口默认隐藏；
 * visible 模式（browser_login / 交互）显示真实窗口供用户操作。
 */

import { randomBytes } from 'node:crypto';
import { basename, join } from 'node:path';
import { BrowserWindow, session } from 'electron';

import {
  startAgentBrowserBridge,
  type AgentBrowserBridgeHandle,
  type BridgeSession,
  type BridgeWindow,
} from './agentBrowserBridge';
import { logger } from './logger';
import { plainChromeUa } from './plainChromeUa';

export const AGENT_BROWSER_PARTITION = 'persist:sage-agent-browser';

function wrapWindow(win: BrowserWindow): BridgeWindow {
  return {
    get webContents() {
      return win.webContents as unknown as BridgeWindow['webContents'];
    },
    show: () => win.show(),
    focus: () => win.focus(),
    close: () => win.close(),
    isDestroyed: () => win.isDestroyed(),
  };
}

function createWindow(partitionSession: Electron.Session, visible: boolean): BridgeWindow {
  const win = new BrowserWindow({
    show: visible,
    width: 1280,
    height: 860,
    title: 'Sage 浏览器',
    webPreferences: {
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false,
      partition: AGENT_BROWSER_PARTITION,
    },
  });
  try {
    const ua = plainChromeUa(win.webContents.getUserAgent());
    partitionSession.setUserAgent(ua);
    win.webContents.setUserAgent(ua);
  } catch {
    // UA 归一化失败不阻断窗口创建（降级为默认 UA）
  }
  // 与主窗口同口径：拒绝弹窗与本地协议导航，缩小登录页面的攻击面。
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (event, url) => {
    if (!/^https?:\/\//i.test(url)) event.preventDefault();
  });
  return wrapWindow(win);
}

/**
 * 启动内置浏览器桥。返回 null 表示启动失败（调用方不注入 env，回落系统浏览器）。
 */
export async function startAgentBrowserHost(): Promise<AgentBrowserBridgeHandle | null> {
  try {
    const partitionSession = session.fromPartition(AGENT_BROWSER_PARTITION);
    partitionSession.setPermissionRequestHandler((_wc, _permission, callback) => {
      callback(false);
    });
    let downloadDir = '';
    const bridgeSession: BridgeSession = {
      cookies: partitionSession.cookies as unknown as BridgeSession['cookies'],
      setDownloadPath: (path: string) => {
        downloadDir = path;
      },
    };
    const handle = await startAgentBrowserBridge({
      createWindow: (visible: boolean) => createWindow(partitionSession, visible),
      getSession: () => bridgeSession,
      randomId: () => randomBytes(8).toString('hex'),
      log: (message: string) => logger.debug(message),
      onDownload: (handler) => {
        partitionSession.on('will-download', (_event, item) => {
          // Electron 默认会弹保存对话框（隐藏窗口下会卡住）；后端已通过
          // Browser.setDownloadBehavior 指定目录，这里直接落盘。
          if (downloadDir) {
            item.setSavePath(join(downloadDir, basename(item.getFilename())));
          }
          const guid = randomBytes(8).toString('hex');
          const emit = (method: string, extra: Record<string, unknown>): void => {
            handler(method, { guid, ...extra });
          };
          emit('Browser.downloadWillBegin', {
            url: item.getURL(),
            suggestedFilename: item.getFilename(),
          });
          item.on('updated', (_e, state) => {
            emit('Browser.downloadProgress', {
              state: state === 'interrupted' ? 'canceled' : 'inProgress',
              receivedBytes: item.getReceivedBytes(),
              totalBytes: item.getTotalBytes(),
            });
          });
          item.once('done', (_e, state) => {
            emit('Browser.downloadProgress', {
              state: state === 'completed' ? 'completed' : 'canceled',
              receivedBytes: item.getReceivedBytes(),
              totalBytes: item.getTotalBytes(),
            });
          });
        });
      },
    });
    logger.info('main: embedded agent browser bridge started', { port: handle.port });
    return handle;
  } catch (error) {
    logger.warn('main: embedded agent browser bridge failed to start', {
      error: error instanceof Error ? error.message : String(error),
    });
    return null;
  }
}
