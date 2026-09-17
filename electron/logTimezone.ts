/**
 * 日志时区持久化 (2026-09-17).
 *
 * 与 closeToTray / demoMode 同模式: 主进程从 userData JSON 文件读取,
 * renderer 通过 IPC 写入. 主进程启动时读一次, 设置 Electron logger 时区.
 *
 * 格式: `{"logTimezone": "UTC"}` (单字段, 便于后续扩展).
 */
import { app } from 'electron';
import { readFileSync, writeFileSync } from 'fs';
import { join } from 'path';

function getLogTimezonePath(): string {
  if (app.isPackaged) return join(app.getPath('userData'), 'sage-log-timezone.json');
  return join(process.cwd(), 'data', 'sage-log-timezone.json');
}

/** 读取持久化的 logTimezone. 失败/缺失返回 'UTC' (历史默认). */
export function readLogTimezone(): string {
  try {
    const raw = readFileSync(getLogTimezonePath(), 'utf-8');
    const parsed = JSON.parse(raw) as { logTimezone?: unknown };
    if (typeof parsed.logTimezone === 'string' && parsed.logTimezone.length > 0) {
      return parsed.logTimezone;
    }
    return 'UTC';
  } catch {
    return 'UTC';
  }
}

/** 写入 logTimezone 到磁盘. 失败静默 (不阻塞 UI). */
export function writeLogTimezone(tz: string): boolean {
  try {
    const content = JSON.stringify({ logTimezone: tz }, null, 2);
    writeFileSync(getLogTimezonePath(), content, 'utf-8');
    return true;
  } catch {
    return false;
  }
}
