// electron/menu.ts

/**
 * Builds the Electron application menu.
 *
 * Currently exposes a minimal file/help menu, with the help submenu
 * providing quick access to the runtime log directory:
 *   - 打开日志目录: opens the log dir in the OS file manager via shell.openPath
 *   - 复制日志路径: copies the log dir path to the clipboard
 *
 * The log dir is resolved from getLogDir() (see electron/logPaths.ts),
 * which honors SAGE_LOG_DIR and falls back to <userData>/logs.
 */

import { Menu, shell, clipboard, app } from 'electron';
import { getLogDir } from './logPaths';
import { logger } from './logger';

export function buildApplicationMenu(): void {
  const isMac = process.platform === 'darwin';
  const logDir = getLogDir();

  const template: Electron.MenuItemConstructorOptions[] = [
    ...(isMac
      ? [
          {
            label: app.name,
            submenu: [
              { role: 'about' as const },
              { type: 'separator' as const },
              { role: 'quit' as const },
            ],
          },
        ]
      : []),
    {
      label: '文件',
      submenu: [isMac ? { role: 'close' } : { role: 'quit' }],
    },
    {
      label: '帮助',
      submenu: [
        {
          label: '打开日志目录',
          click: () => {
            logger.info('main: user opened log dir via menu', { logDir });
            shell
              .openPath(logDir)
              .catch((err) => logger.error('main: shell.openPath failed', { err: String(err) }));
          },
        },
        {
          label: '复制日志路径',
          click: () => {
            clipboard.writeText(logDir);
            logger.info('main: user copied log dir via menu', { logDir });
          },
        },
      ],
    },
  ];

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
}