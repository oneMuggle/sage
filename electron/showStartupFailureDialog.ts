// electron/showStartupFailureDialog.ts

/**
 * Startup-failure dialog — shows a 3- or 4-button message box when Sage fails to launch.
 *
 * Buttons (in order, when `diagnosticPath` is supplied):
 *   1. 打开诊断目录 — shell.openPath() on the diagnostic directory
 *   2. 打开日志目录 — shell.openPath() on the Sage log directory
 *   3. 重试
 *   4. 退出
 *
 * Buttons (when no `diagnosticPath`):
 *   1. 打开日志目录
 *   2. 重试
 *   3. 退出
 *
 * CRITICAL: `logger.error(...)` MUST be invoked BEFORE `dialog.showMessageBox`,
 * so that even if the dialog itself crashes, the failure is already on disk.
 */

import { dialog, shell, app } from 'electron';
import { dirname } from 'node:path';
import { getLogDir } from './logPaths';
import { logger } from './logger';

export type StartupFailureChoice = 'open-diagnostic' | 'open-logs' | 'retry' | 'quit';

export async function showStartupFailureDialog(opts: {
  reason: string;
  detail?: string;
  diagnosticPath?: string;
}): Promise<StartupFailureChoice> {
  // CRITICAL: write to log BEFORE showing dialog (so even if dialog crashes
  // the failure is captured on disk)
  logger.error('main: startup failed, showing dialog', {
    reason: opts.reason,
    detail: opts.detail,
    diagnosticPath: opts.diagnosticPath,
  });

  const logDir = getLogDir();
  const hasDiag = !!opts.diagnosticPath;
  // Button order is meaningful: Electron highlights index `defaultId`. We keep
  // the high-frequency "retry" action in the same physical position whether
  // or not the diagnostic button is present (defaultId=1 with diag else 0).
  const buttons = hasDiag
    ? ['打开诊断目录', '打开日志目录', '重试', '退出']
    : ['打开日志目录', '重试', '退出'];
  const defaultId = hasDiag ? 2 : 1;
  const cancelId = hasDiag ? 3 : 2;
  const result = await dialog.showMessageBox({
    type: 'error',
    title: 'Sage 启动失败',
    message: opts.reason,
    detail: `${opts.detail ?? ''}\n\n错误详情已写入日志${
      hasDiag ? '和诊断文件' : ''
    }，请点击下方按钮获取${
      hasDiag ? '诊断/日志' : '日志'
    }文件并附在反馈中。\n\n日志目录：${logDir}${
      hasDiag ? `\n诊断文件：${opts.diagnosticPath}` : ''
    }`,
    buttons,
    defaultId,
    cancelId,
    noLink: true,
  });

  let choice: StartupFailureChoice;
  if (hasDiag) {
    choice =
      result.response === 0
        ? 'open-diagnostic'
        : result.response === 1
          ? 'open-logs'
          : result.response === 2
            ? 'retry'
            : 'quit';
  } else {
    choice =
      result.response === 0 ? 'open-logs' : result.response === 1 ? 'retry' : 'quit';
  }

  if (choice === 'open-diagnostic' && opts.diagnosticPath) {
    logger.info('main: user chose open-diagnostic after startup failure');
    Promise.resolve(shell.openPath(dirname(opts.diagnosticPath))).catch((err) =>
      logger.error('main: shell.openPath(diag dir) failed', { err: String(err) })
    );
  } else if (choice === 'open-logs') {
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