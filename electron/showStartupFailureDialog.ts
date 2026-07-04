// electron/showStartupFailureDialog.ts

/**
 * Startup-failure dialog — shows a 3-button message box when Sage fails to launch.
 *
 * Buttons (in order): 打开日志目录 / 重试 / 退出
 *
 * CRITICAL: `logger.error(...)` MUST be invoked BEFORE `dialog.showMessageBox`,
 * so that even if the dialog itself crashes, the failure is already on disk.
 */

import { dialog, shell, app } from 'electron';
import { getLogDir } from './logPaths';
import { logger } from './logger';

export type StartupFailureChoice = 'open-logs' | 'retry' | 'quit';

export async function showStartupFailureDialog(opts: {
  reason: string;
  detail?: string;
}): Promise<StartupFailureChoice> {
  // CRITICAL: write to log BEFORE showing dialog (so even if dialog crashes
  // the failure is captured on disk)
  logger.error('main: startup failed, showing dialog', {
    reason: opts.reason,
    detail: opts.detail,
  });

  const logDir = getLogDir();
  const buttons = ['打开日志目录', '重试', '退出'];
  const result = await dialog.showMessageBox({
    type: 'error',
    title: 'Sage 启动失败',
    message: opts.reason,
    detail: `${opts.detail ?? ''}\n\n错误详情已写入日志，请点击下方按钮获取日志文件并附在反馈中。\n\n日志目录：${logDir}`,
    buttons,
    defaultId: 0,
    cancelId: 2,
    noLink: true,
  });

  const choice: StartupFailureChoice =
    result.response === 0 ? 'open-logs' : result.response === 1 ? 'retry' : 'quit';

  if (choice === 'open-logs') {
    logger.info('main: user chose open-logs after startup failure');
    Promise.resolve(shell.openPath(logDir)).catch((err) =>
      logger.error('main: shell.openPath failed', { err: String(err) })
    );
  } else if (choice === 'retry') {
    logger.info('main: user chose retry after startup failure');
  } else {
    logger.info('main: user chose quit after startup failure');
    app.quit();
  }
  return choice;
}