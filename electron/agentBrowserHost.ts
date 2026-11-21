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
import { app, BrowserWindow, session } from 'electron';

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
  // 与主窗口同口径：本地/自定义协议一律拒绝。但 http(s) 弹窗需放行——知网等
  // 检索入口依赖 window.open 的隐藏小窗建立代理会话（随即自行关闭），一律 deny
  // 会让这类站点直接死路（页面提示「弹窗被拦截」）。放行时强制沙箱化子窗口并
  // 继承持久分区；页面文本仍按不可信数据处理，站点策略在工具动作前复核域名。
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (!/^https?:\/\//i.test(url)) return { action: 'deny' };
    return {
      action: 'allow',
      overrideBrowserWindowOptions: {
        show: true,
        webPreferences: {
          sandbox: true,
          contextIsolation: true,
          nodeIntegration: false,
          partition: AGENT_BROWSER_PARTITION,
        },
      },
    };
  });
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
          // Electron 默认会弹保存对话框（隐藏/受控窗口下无人可点 → 下载卡死）。
          // 后端通常已通过 Browser.setDownloadBehavior 指定目录；若尚未设置
          // （例如 navigate 自动拉起后后端漏调），兜底写入系统下载目录，
          // 任何情况下都不允许弹对话框。
          const saveDir = downloadDir || app.getPath('downloads');
          try {
            item.setSavePath(join(saveDir, basename(item.getFilename())));
          } catch {
            // setSavePath 失败时保持默认行为，不阻断事件上报
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
