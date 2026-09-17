// electron/crashGuard.ts

/**
 * Crash event capture — Electron main process last-resort safety net.
 *
 * 背景 (2026-09-17):
 *   内网部分 Win7 SP1 机器在 Sage 启动时闪退, 但闪退现场没有任何 NDJSON 记录.
 *   根因是 Chromium 106 找不到关键系统 DLL → 主进程/子进程 abort → 进程消失,
 *   logger 根本来不及写盘.
 *
 * 解决方案: 注册三类 catch-all 事件, 把异常 dump 到独立 emergency log + 让
 * Electron 内置 crashReporter 写 minidump. emergency log 是 plain text append
 * (不依赖 logger / 不依赖 userData 日志目录存在), 即使全部基础设施都炸了
 * 也能留下痕迹.
 *
 * 设计要点:
 *   - emergency log 路径 = `<userData>/sage-emergency.log`
 *     (与 logger.ts 独立, logger 写不下时这里还能写)
 *   - 所有写盘都用 try/catch 包住 — 这是 last resort, 自己不能再 throw
 *   - 不在 module top-level 用 logger: logger 可能没初始化 / userData 还没就绪
 *   - 必须放在 main.ts 顶部最先 import, 早于 logger / BrowserWindow 等
 */

import { app, dialog, crashReporter } from 'electron';
import { appendFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

// ── emergency log ────────────────────────────────────────────────────────────

let emergencyLogPath: string | null = null;

function getEmergencyLogPath(): string {
  if (emergencyLogPath) return emergencyLogPath;
  try {
    const userData = app.getPath('userData');
    if (!userData) throw new Error('app.getPath(userData) returned empty');
    try {
      mkdirSync(userData, { recursive: true });
    } catch {
      // ignore: dir may already exist
    }
    emergencyLogPath = join(userData, 'sage-emergency.log');
  } catch (err) {
    emergencyLogPath = '/tmp/sage-emergency.log';
    appendFileSync(
      emergencyLogPath,
      `[${new Date().toISOString()}] crashGuard: failed to resolve userData, falling back to ${emergencyLogPath} (${String(err)})\n`,
    );
  }
  return emergencyLogPath;
}

export function emergencyLog(label: string, payload: unknown): void {
  try {
    const path = getEmergencyLogPath();
    appendFileSync(path, `[${new Date().toISOString()}] ${label} ${safeStringify(payload)}\n`);
  } catch {
    // last-resort silently drop
  }
}

function safeStringify(v: unknown): string {
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

// ── process-level handlers ───────────────────────────────────────────────────

process.on('uncaughtException', (err: Error, origin: NodeJS.UncaughtExceptionOrigin) => {
  emergencyLog('process:uncaughtException', {
    err: err?.message ?? String(err),
    stack: err?.stack,
    origin,
    pid: process.pid,
  });
  try {
    const path = getEmergencyLogPath();
    dialog.showErrorBox(
      'Sage 启动失败',
      `未捕获异常: ${err?.message ?? String(err)}\n\n详情已写入紧急日志:\n${path}`,
    );
  } catch {
    // dialog may fail if X server broken or already crashed
  }
});

process.on('unhandledRejection', (reason: unknown) => {
  emergencyLog('process:unhandledRejection', {
    reason: reason instanceof Error ? reason.message : String(reason),
    stack: reason instanceof Error ? reason.stack : undefined,
    pid: process.pid,
  });
});

// ── Electron app-level handlers ──────────────────────────────────────────────

app.on('render-process-gone', (_event, _webContents, details) => {
  emergencyLog('app:render-process-gone', {
    reason: details?.reason,
    exitCode: details?.exitCode,
    pid: process.pid,
  });
});

app.on('child-process-gone', (_event, details) => {
  emergencyLog('app:child-process-gone', {
    type: details?.type,
    reason: details?.reason,
    exitCode: details?.exitCode,
    serviceName: details?.serviceName,
    pid: process.pid,
  });
});

app.on('gpu-process-crashed', (_event, killed) => {
  emergencyLog('app:gpu-process-crashed', {
    killed,
    pid: process.pid,
  });
});

app.on('renderer-process-crashed', (_event, _webContents, killed) => {
  emergencyLog('app:renderer-process-crashed', {
    killed,
    pid: process.pid,
  });
});

// ── crash reporter ───────────────────────────────────────────────────────────

try {
  crashReporter.start({
    productName: 'Sage',
    companyName: 'Sage',
    submitURL: '',
    compress: true,
    ignoreSystemCrashHandler: false,
  });
  emergencyLog('crashReporter:start', {
    crashDumps: app.getPath('crashDumps'),
    pid: process.pid,
  });
} catch (err) {
  emergencyLog('crashReporter:start failed', {
    err: err instanceof Error ? err.message : String(err),
    pid: process.pid,
  });
}

emergencyLog('crashGuard:loaded', { pid: process.pid, electron: process.versions.electron });