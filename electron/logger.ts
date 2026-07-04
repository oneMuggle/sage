// electron/logger.ts

/**
 * Electron main process logger — NDJSON file logger with level filtering.
 *
 * Wraps electron-log (4.x, Win7-compatible) for file persistence + rotation,
 * and exposes a thin level-aware API for the rest of the main process.
 *
 * Output: <userData>/logs/sage-YYYY-MM-DD.ndjson (NDJSON, one event per line)
 *
 * Lifecycle:
 *   - Module load: reads SAGE_LOG_DIR / SAGE_LOG_LEVEL env, configures electron-log
 *   - First call to logger.*: ensures log directory exists
 *   - Each call: writes one NDJSON line with ts/level/source/msg/meta
 *
 * Renderer-side logs come through IPC (sage:log:write), handled in logIpc.ts.
 */

import log from 'electron-log';
import { appendFileSync, mkdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { app } from 'electron';
import type { LogLevel } from '../src/shared/log/levels';
import { LOG_LEVELS, DEFAULT_LOG_LEVEL } from '../src/shared/log/levels';

const SOURCE = 'main';

function resolveLogDir(): string {
  const base = process.env.SAGE_LOG_DIR
    ? process.env.SAGE_LOG_DIR
    : (() => {
        try {
          return app.getPath('userData');
        } catch {
          return process.cwd();
        }
      })();
  return join(base, 'logs');
}

function resolveLevel(): LogLevel {
  const env = process.env.SAGE_LOG_LEVEL as LogLevel | undefined;
  if (env && env in LOG_LEVELS) return env;
  return DEFAULT_LOG_LEVEL;
}

const LOG_DIR = resolveLogDir();
const CURRENT_LEVEL = resolveLevel();

try {
  mkdirSync(LOG_DIR, { recursive: true });
  log.transports.file.resolvePath = () => join(LOG_DIR, 'electron-log-fallback.log');
  log.transports.file.level = CURRENT_LEVEL;
  log.transports.console.level = process.env.NODE_ENV === 'production' ? 'warn' : 'debug';
} catch (err) {
  console.error('[logger] failed to configure transports:', err);
}

function shouldLog(level: LogLevel): boolean {
  return LOG_LEVELS[level] >= LOG_LEVELS[CURRENT_LEVEL];
}

function safeStringify(value: unknown): unknown {
  const seen = new WeakSet();
  const replacer = (_key: string, val: unknown): unknown => {
    if (typeof val === 'function' || typeof val === 'symbol') return '[unserializable]';
    if (typeof val === 'bigint') return val.toString();
    if (val !== null && typeof val === 'object') {
      if (seen.has(val)) return '[unserializable]';
      seen.add(val);
    }
    return val;
  };
  try {
    return JSON.parse(JSON.stringify(value, replacer));
  } catch {
    return '[unserializable]';
  }
}

function writeLine(level: LogLevel, source: string, msg: string, meta?: unknown): void {
  const line: Record<string, unknown> = {
    ts: new Date().toISOString(),
    level,
    source,
    msg,
  };
  if (meta !== undefined) {
    line.meta = safeStringify(meta);
  }
  const today = new Date().toISOString().slice(0, 10);
  const file = join(LOG_DIR, `sage-${today}.ndjson`);
  try {
    if (!existsSync(LOG_DIR)) mkdirSync(LOG_DIR, { recursive: true });
    appendFileSync(file, JSON.stringify(line) + '\n', 'utf-8');
  } catch (err) {
    console.error('[logger] failed to write log line:', err);
  }
}

function logIt(level: LogLevel, msg: string, meta?: unknown, source: string = SOURCE): void {
  if (!shouldLog(level)) return;
  writeLine(level, source, msg, meta);
  try {
    const electronLogMethod = (log as unknown as Record<string, (m: string) => void>)[level];
    if (electronLogMethod) electronLogMethod.call(log, `[${source}] ${msg}`);
  } catch {
    /* ignore */
  }
}

export const logger = {
  debug(msg: string, meta?: unknown): void {
    logIt('debug', msg, meta);
  },
  info(msg: string, meta?: unknown): void {
    logIt('info', msg, meta);
  },
  warn(msg: string, meta?: unknown): void {
    logIt('warn', msg, meta);
  },
  error(msg: string, meta?: unknown): void {
    logIt('error', msg, meta);
  },
  /** Internal: log with explicit source (used by logIpc for renderer events). */
  _logFromSource(level: LogLevel, source: string, msg: string, meta?: unknown): void {
    logIt(level, msg, meta, source);
  },
};
