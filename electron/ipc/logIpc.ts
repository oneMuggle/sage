// electron/ipc/logIpc.ts
import type { IpcMain } from 'electron';
import type { LogLevel } from '../../src/shared/log/levels';
import { logger } from '../logger';
import { RATE_LIMIT_WARN_INTERVAL_MS } from '../../src/shared/log/levels';

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
}
