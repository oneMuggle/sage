// electron/ipc/logIpc.ts
import type { IpcMain } from 'electron';
import { shell, clipboard } from 'electron';
import { readdirSync, statSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import type { LogLevel } from '../../src/shared/log/levels';
import { logger } from '../logger';
import { RATE_LIMIT_WARN_INTERVAL_MS } from '../../src/shared/log/levels';
import { cleanupOlderThan } from '../logRotate';
import { getLogDir } from '../logPaths';

interface LogPayload {
  level: LogLevel;
  msg: string;
  meta?: Record<string, unknown>;
}

const RATE_LIMIT_PER_SEC = 100;

interface SenderState {
  windowStartMs: number;
  count: number;
  lastWarnMs: number;
}
const senderState = new Map<number, SenderState>();

function checkRateLimit(senderId: number): boolean {
  const now = Date.now();
  let state = senderState.get(senderId);
  if (!state || now - state.windowStartMs >= 1000) {
    state = { windowStartMs: now, count: 0, lastWarnMs: 0 };
    senderState.set(senderId, state);
  }
  state.count++;
  if (state.count > RATE_LIMIT_PER_SEC) {
    if (now - state.lastWarnMs >= RATE_LIMIT_WARN_INTERVAL_MS) {
      state.lastWarnMs = now;
      logger.warn('renderer log rate limited', {
        senderId,
        dropped: state.count - RATE_LIMIT_PER_SEC,
      });
    }
    return false;
  }
  return true;
}

export function registerLogIpc(ipcMain: IpcMain): void {
  ipcMain.handle('sage:log:write', async (evt, payload: LogPayload) => {
    const senderId = evt.sender.id;
    if (!checkRateLimit(senderId)) return { ok: false, reason: 'rate-limited' };
    logger._logFromSource(payload.level, 'renderer', payload.msg, payload.meta);
    return { ok: true };
  });

  /**
   * T13 (2026-07-02): Log management handlers — Diagnostics card.
   * All return plain serializable values; renderer invokes via window.electronAPI.*.
   */

  ipcMain.handle('sage:log:list-files', async () => {
    const dir = getLogDir();
    if (!existsSync(dir)) return [];
    const entries = readdirSync(dir);
    return entries
      .filter((n) => /^sage-\d{4}-\d{2}-\d{2}\.ndjson/.test(n))
      .map((name) => {
        const full = join(dir, name);
        const st = statSync(full);
        return { name, sizeBytes: st.size, mtimeMs: st.mtimeMs };
      })
      .sort((a, b) => b.mtimeMs - a.mtimeMs);
  });

  ipcMain.handle('sage:log:open-dir', async () => {
    const dir = getLogDir();
    await shell.openPath(dir);
    return dir;
  });

  ipcMain.handle('sage:log:copy-path', async () => {
    const dir = getLogDir();
    clipboard.writeText(dir);
    return dir;
  });

  ipcMain.handle('sage:log:cleanup', async () => {
    const dir = getLogDir();
    if (!existsSync(dir)) return { removed: 0 };
    const before = readdirSync(dir).length;
    cleanupOlderThan(7);
    const after = readdirSync(dir).length;
    return { removed: before - after };
  });

  ipcMain.handle(
    'sage:log:set-level',
    async (_evt, payload: { level: LogLevel }) => {
      process.env.SAGE_LOG_LEVEL = payload.level;
      logger.info('main: log level changed', { level: payload.level });
      return { ok: true };
    },
  );
}
