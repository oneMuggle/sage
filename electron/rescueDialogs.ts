/**
 * rescueDialogs — 不依赖 renderer 的原生恢复对话框 / 修复工具入口。
 *
 * 用途：
 * - renderer 崩溃 / 心跳丢失时弹「安全模式重启 / 运行修复工具 / 生成诊断包 / 退出」；
 * - 启动失败对话框与托盘/菜单复用「运行修复工具」和「生成诊断包」。
 *
 * 所有操作都走 `dialog` / `shell` / bundled python CLI，不依赖前端可用。
 */
import { app, dialog, shell } from 'electron';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';

import { logger } from './logger';
import { resolveSageDbPath, resolveSageUserDataDir } from './userDataPaths';

export type RecoveryChoice = 'safe-mode' | 'repair-tool' | 'report' | 'quit';

export interface RecoveryDialogOptions {
  crashCount: number;
  reason: string;
  safeModeLevel: number;
}

/** 解析安装目录中的 SageDoctor.cmd（打包模式）；dev 模式返回 resources/SageDoctor.cmd。 */
export function resolveRescueLauncherPath(): string | null {
  const candidates: string[] = [];
  if (app.isPackaged) {
    candidates.push(join(dirname(app.getPath('exe')), 'SageDoctor.cmd'));
  }
  candidates.push(join(process.cwd(), 'resources', 'SageDoctor.cmd'));
  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

/** 打开控制台修复工具。返回是否成功发起。 */
export async function openRescueTool(): Promise<boolean> {
  // 非 Windows dev 环境无法执行 .cmd；提示开发者直接运行 CLI。
  if (!app.isPackaged && process.platform !== 'win32') {
    try {
      await dialog.showMessageBox({
        type: 'info',
        title: 'Sage 修复工具',
        message: '开发模式下请在终端运行：',
        detail: 'python -m backend.cli.rescue',
        buttons: ['确定'],
        noLink: true,
      });
    } catch (err) {
      logger.warn('rescue: dev hint dialog failed', { err: String(err) });
    }
    return false;
  }
  const launcher = resolveRescueLauncherPath();
  if (!launcher) {
    await dialog.showMessageBox({
      type: 'warning',
      title: 'Sage 修复工具',
      message: '未找到 SageDoctor.cmd',
      detail: '请确认 Sage 安装完整；开发模式下可手动运行：\n\n' + '  python -m backend.cli.rescue',
      buttons: ['确定'],
      noLink: true,
    });
    return false;
  }
  try {
    await shell.openPath(launcher);
    logger.info('rescue: opened repair tool', { launcher });
    return true;
  } catch (err) {
    logger.error('rescue: failed to open repair tool', {
      launcher,
      err: err instanceof Error ? err.message : String(err),
    });
    return false;
  }
}

/**
 * 运行 `python -m backend.cli.rescue report`（不依赖后端）。
 * 返回输出末尾（包含支持包路径）供对话框展示。
 */
export async function runRescueReport(): Promise<{ ok: boolean; message: string }> {
  const plan = resolveRescueSpawnPlan();
  if (!plan) {
    return { ok: false, message: '未找到 Sage 内置 Python 运行时，无法生成诊断包。' };
  }
  return new Promise((resolve) => {
    let output = '';
    let settled = false;
    const finish = (ok: boolean, message: string) => {
      if (settled) return;
      settled = true;
      resolve({ ok, message });
    };
    try {
      const child = spawn(plan.command, plan.args, {
        cwd: plan.cwd,
        env: { ...process.env, ...plan.env },
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      child.stdout?.on('data', (chunk: Buffer) => {
        output += chunk.toString('utf-8');
      });
      child.stderr?.on('data', (chunk: Buffer) => {
        output += chunk.toString('utf-8');
      });
      child.on('error', (err) => finish(false, `启动失败: ${err.message}`));
      child.on('close', (code) => {
        const tail = output.trim().split('\n').slice(-4).join('\n');
        finish(code === 0, tail || `退出码 ${code}`);
      });
      setTimeout(() => {
        if (!settled) {
          try {
            child.kill();
          } catch {
            // ignore
          }
          finish(false, '生成诊断包超时（60s）');
        }
      }, 60_000).unref?.();
    } catch (err) {
      finish(false, err instanceof Error ? err.message : String(err));
    }
  });
}

interface RescueSpawnPlan {
  command: string;
  args: string[];
  cwd: string;
  env: Record<string, string>;
}

function resolveRescueSpawnPlan(): RescueSpawnPlan | null {
  // 打包模式：<install>/resources/python/python.exe
  if (app.isPackaged) {
    const resources = process.resourcesPath;
    const pythonExe = join(resources, 'python', 'python.exe');
    if (existsSync(pythonExe)) {
      const sep = process.platform === 'win32' ? ';' : ':';
      return {
        command: pythonExe,
        args: ['-m', 'backend.cli.rescue', 'report'],
        cwd: resources,
        env: {
          SAGE_IS_PACKAGED: '1',
          SAGE_USER_DATA_DIR: app.getPath('userData'),
          SAGE_DB_PATH: join(app.getPath('userData'), 'sage.db'),
          PYTHONPATH: [join(resources, 'backend'), join(resources, 'sage-core')].join(sep),
        },
      };
    }
    return null;
  }
  // dev：优先 SAGE_PYTHON，其次 python；userData/DB 路径与 Electron dev 保持一致。
  const python = process.env.SAGE_PYTHON ?? process.env.PYTHON ?? 'python';
  return {
    command: python,
    args: ['-m', 'backend.cli.rescue', 'report'],
    cwd: process.cwd(),
    env: {
      SAGE_USER_DATA_DIR: resolveSageUserDataDir(),
      SAGE_DB_PATH: resolveSageDbPath(),
    },
  };
}

/** 弹原生恢复对话框；不依赖 renderer。 */
export async function showCrashRecoveryDialog(
  opts: RecoveryDialogOptions,
): Promise<RecoveryChoice> {
  const buttons = ['安全模式重启', '运行修复工具', '生成诊断包', '退出'];
  let response = 3;
  try {
    const result = await dialog.showMessageBox({
      type: 'warning',
      title: 'Sage 窗口意外关闭',
      message: `检测到前端进程异常退出（第 ${opts.crashCount} 次）`,
      detail:
        `原因: ${opts.reason}\n当前兼容档位: L${opts.safeModeLevel}\n\n` +
        '可以选择以安全模式重启（再次降低渲染复杂度），或运行修复工具配置端点/生成诊断包。',
      buttons,
      defaultId: 0,
      cancelId: 3,
      noLink: true,
    });
    response = result.response;
  } catch (err) {
    logger.error('rescue: showCrashRecoveryDialog failed', {
      err: err instanceof Error ? err.message : String(err),
    });
  }
  if (response === 0) return 'safe-mode';
  if (response === 1) return 'repair-tool';
  if (response === 2) return 'report';
  return 'quit';
}
