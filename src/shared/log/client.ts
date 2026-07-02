// src/shared/log/client.ts
import type { LogLevel } from './levels';

function send(level: LogLevel, msg: string, meta?: Record<string, unknown>): void {
  const api = typeof window !== 'undefined' ? window.electronAPI?.log : undefined;
  if (!api) {
    if (import.meta.env?.DEV) {
      // eslint-disable-next-line no-console
      console[level === 'debug' ? 'debug' : level === 'warn' ? 'warn' : level](
        `[renderer] ${msg}`,
        meta,
      );
    }
    return;
  }
  api(level, msg, meta).catch(() => {
    /* IPC failed; no UI fallback to avoid infinite loops */
  });
}

export const clientLogger = {
  debug(msg: string, meta?: Record<string, unknown>): void {
    send('debug', msg, meta);
  },
  info(msg: string, meta?: Record<string, unknown>): void {
    send('info', msg, meta);
  },
  warn(msg: string, meta?: Record<string, unknown>): void {
    send('warn', msg, meta);
  },
  error(msg: string, meta?: Record<string, unknown>): void {
    send('error', msg, meta);
  },
};
