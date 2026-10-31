/**
 * 应用内浏览器面板（P2）：右栏「浏览器」Tab 的 Electron BrowserView 宿主。
 *
 * - 与内置 Agent 浏览器共享 `persist:sage-agent-browser` 分区：面板里登录一次，
 *   agent 的 embedded 通道立即复用同一 cookie/localStorage；
 * - bounds 由渲染层 `getBoundingClientRect` 上报，主进程钳制到窗口内容区域；
 * - 安全基线：sandbox / contextIsolation / no Node / 拒绝权限请求 / 仅 http(s)。
 *
 * 通过 `sage:invoke` 的 `browser_panel` 命令调用（action 参数），避免新增 IPC 通道。
 */

import { BrowserView, BrowserWindow, session, type WebContents } from 'electron';

const PANEL_PARTITION = 'persist:sage-agent-browser';

interface PanelState {
  view: BrowserView;
  bounds: { x: number; y: number; width: number; height: number };
}

const panels = new WeakMap<BrowserWindow, PanelState>();

function isHttpUrl(value: string): boolean {
  return /^https?:\/\//i.test(value.trim());
}

function clampRect(
  win: BrowserWindow,
  rect: { x: number; y: number; width: number; height: number },
): { x: number; y: number; width: number; height: number } {
  const [winWidth, winHeight] = win.getContentSize();
  const x = Math.max(0, Math.min(Math.round(rect.x), Math.max(0, winWidth - 1)));
  const y = Math.max(0, Math.min(Math.round(rect.y), Math.max(0, winHeight - 1)));
  const width = Math.max(1, Math.min(Math.round(rect.width), winWidth - x));
  const height = Math.max(1, Math.min(Math.round(rect.height), winHeight - y));
  return { x, y, width, height };
}

function ensurePanel(win: BrowserWindow): PanelState {
  const existing = panels.get(win);
  if (existing && !existing.view.webContents.isDestroyed()) return existing;

  const partition = session.fromPartition(PANEL_PARTITION);
  partition.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));

  const view = new BrowserView({
    webPreferences: {
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false,
      partition: PANEL_PARTITION,
    },
  });
  view.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  view.webContents.on('will-navigate', (event, url) => {
    if (!/^https?:\/\//i.test(url)) event.preventDefault();
  });
  view.setAutoResize({ width: true, height: true });

  const state: PanelState = {
    view,
    bounds: { x: 0, y: 0, width: 1, height: 1 },
  };
  panels.set(win, state);
  return state;
}

function requirePanel(win: BrowserWindow | null): { win: BrowserWindow; state: PanelState } {
  if (!win || win.isDestroyed()) throw new Error('browser panel: no window');
  const state = panels.get(win);
  if (!state || state.view.webContents.isDestroyed()) {
    throw new Error('browser panel: not shown');
  }
  return { win, state };
}

export function handleBrowserPanelCommand(
  sender: WebContents,
  args: Record<string, unknown>,
): unknown {
  const win = BrowserWindow.fromWebContents(sender);
  if (!win || win.isDestroyed()) throw new Error('browser panel: untrusted window');
  const action = String(args.action ?? '');

  switch (action) {
    case 'show': {
      const state = ensurePanel(win);
      win.setBrowserView(state.view);
      state.view.setBounds(clampRect(win, state.bounds));
      return { ok: true, url: state.view.webContents.getURL() };
    }
    case 'hide': {
      const state = panels.get(win);
      if (state) {
        win.removeBrowserView(state.view);
        const contents = state.view.webContents as unknown as {
          close?: () => void;
          destroy?: () => void;
        };
        if (typeof contents.close === 'function') contents.close();
        else contents.destroy?.();
        panels.delete(win);
      }
      return { ok: true };
    }
    case 'setBounds': {
      const { state } = requirePanel(win);
      const rect = args.rect as
        | { x?: unknown; y?: unknown; width?: unknown; height?: unknown }
        | undefined;
      if (!rect) throw new Error('browser panel: rect required');
      const raw = {
        x: Number(rect.x),
        y: Number(rect.y),
        width: Number(rect.width),
        height: Number(rect.height),
      };
      if (!Object.values(raw).every((value) => Number.isFinite(value))) {
        throw new Error('browser panel: invalid rect');
      }
      state.bounds = clampRect(win, raw);
      state.view.setBounds(state.bounds);
      return { ok: true };
    }
    case 'navigate': {
      const { state } = requirePanel(win);
      const url = String(args.url ?? '').trim();
      if (!isHttpUrl(url)) throw new Error('browser panel: only http(s) URLs are allowed');
      void state.view.webContents.loadURL(url);
      return { ok: true };
    }
    case 'back': {
      const { state } = requirePanel(win);
      if (state.view.webContents.canGoBack()) state.view.webContents.goBack();
      return { ok: true };
    }
    case 'forward': {
      const { state } = requirePanel(win);
      if (state.view.webContents.canGoForward()) state.view.webContents.goForward();
      return { ok: true };
    }
    case 'reload': {
      const { state } = requirePanel(win);
      state.view.webContents.reload();
      return { ok: true };
    }
    case 'current': {
      const { state } = requirePanel(win);
      return {
        url: state.view.webContents.getURL(),
        title: state.view.webContents.getTitle(),
        canGoBack: state.view.webContents.canGoBack(),
        canGoForward: state.view.webContents.canGoForward(),
      };
    }
    default:
      throw new Error(`browser panel: unsupported action: ${action}`);
  }
}
