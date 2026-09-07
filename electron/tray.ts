/**
 * U12 (round4 批次 E): 桌面壳 MVP —— 系统托盘 + 全局快捷键唤起。
 *
 * - 托盘：显示 Sage / 退出 菜单，左键点击唤起主窗口；
 * - 全局快捷键 Alt+Shift+S：任意应用下 toggle 显示/隐藏主窗口；
 * - 失败降级：托盘图标不可用或快捷键被占用只记日志，绝不阻断启动；
 * - 退出清理：will-quit 时 unregisterAll + destroy 托盘。
 *
 * 刻意不做的部分（避免改变用户预期，后续批次再评审）：
 * 关闭按钮仍然正常退出应用，不做"关闭即隐藏到托盘"。
 */
import { app, BrowserWindow, globalShortcut, Menu, Tray } from 'electron';
import { join } from 'path';

import { logger } from './logger';
import { mainWindow } from './mainWindow';

let tray: Tray | null = null;

/** 与 createMainWindow 的窗口图标同源（build/ 随打包资源分发） */
function resolveIconPath(): string {
  return join(__dirname, '..', 'build', 'icon.ico');
}

function showMainWindow(): void {
  const win = mainWindow ?? BrowserWindow.getAllWindows()[0];
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

function toggleMainWindow(): void {
  const win = mainWindow ?? BrowserWindow.getAllWindows()[0];
  if (!win) return;
  if (win.isVisible() && win.isFocused()) {
    win.hide();
  } else {
    showMainWindow();
  }
}

export function setupTrayAndGlobalShortcut(): void {
  try {
    tray = new Tray(resolveIconPath());
    tray.setToolTip('Sage');
    tray.setContextMenu(
      Menu.buildFromTemplate([
        { label: '显示 Sage', click: () => showMainWindow() },
        { type: 'separator' },
        { label: '退出', click: () => void app.quit() },
      ]),
    );
    tray.on('click', () => showMainWindow());
  } catch (err) {
    // 托盘是增强体验——桌面环境不支持时降级为纯窗口应用
    logger.warn('tray: setup failed (continuing without tray)', {
      err: err instanceof Error ? err.message : String(err),
    });
    tray = null;
  }

  const accelerator = 'Alt+Shift+S';
  try {
    // register 返回 false = 被其它应用占用;不抛错
    const registered = globalShortcut.register(accelerator, () => toggleMainWindow());
    if (!registered) {
      logger.warn('tray: global shortcut occupied, skipping', { accelerator });
    }
  } catch (err) {
    logger.warn('tray: global shortcut register failed', {
      accelerator,
      err: err instanceof Error ? err.message : String(err),
    });
  }

  app.on('will-quit', () => {
    try {
      globalShortcut.unregisterAll();
    } catch {
      /* 退出路径上的清理失败无需处理 */
    }
    destroyTray();
  });
}

function destroyTray(): void {
  if (tray) {
    try {
      tray.destroy();
    } catch {
      /* ignore */
    }
    tray = null;
  }
}
