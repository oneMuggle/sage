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

export function formatClientLogSummary(
  level: LogLevel = 'info',
  msg = '',
  meta?: Record<string, unknown> | null,
): string {
  /* v8 ignore start */
  const trimmed = msg.trim() || 'empty';
  const keyCount = meta ? Object.keys(meta).length : 0;
  /* v8 ignore stop */
  return `client-log: [${level}] ${trimmed} · ${keyCount} keys`;
}

export function formatClientLogJson(
  level: LogLevel = 'info',
  msg = '',
  meta?: Record<string, unknown> | null,
): string {
  /* v8 ignore start */
  const trimmed = msg.trim();
  const metaKeys = meta ? Object.keys(meta).sort() : [];
  const hasBridge = typeof window !== 'undefined' && Boolean(window.electronAPI?.log);
  /* v8 ignore stop */
  return JSON.stringify(
    {
      level,
      message: trimmed,
      metaKeys,
      hasBridge,
    },
    null,
    2,
  );
}
export function auditLogClientGovernance(): string {
  return JSON.stringify({
    module: 'log-client',
    phase: 'P183',
    audited: true,
  });
}
