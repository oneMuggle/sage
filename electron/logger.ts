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
// 循环依赖说明: logRotate → logger (仅在其函数体内引用 logger), logger →
// logRotate (仅在 maybeRotateCurrentLog 内引用), 双方都不在模块顶层调用
// 对方导出 —— CJS 下运行时属性访问, 良性。
import { rotateIfOversized } from './logRotate';

const SOURCE = 'main';

// S4 (P3 安全批次): rotateIfOversized 此前无调用点, 单日日志可无限膨胀。
// 按写入字节累计, 每超过 512KB 检查一次当日文件是否达到 10MB 轮转阈值
// —— 避免 Every-line statSync 的开销。
const ROTATE_CHECK_INTERVAL_BYTES = 512 * 1024;
let uncheckedLogBytes = 0;

function maybeRotateCurrentLog(lineBytes: number): void {
  uncheckedLogBytes += lineBytes;
  if (uncheckedLogBytes < ROTATE_CHECK_INTERVAL_BYTES) return;
  uncheckedLogBytes = 0;
  try {
    rotateIfOversized();
  } catch {
    /* 轮转失败不影响日志写入 */
  }
}

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
let CURRENT_LEVEL = resolveLevel();

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
    const serialized = JSON.stringify(line) + '\n';
    appendFileSync(file, serialized, 'utf-8');
    maybeRotateCurrentLog(serialized.length);
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

/** 运行时切换日志级别(日志基线修复 #2)。无效级别忽略,保持 CURRENT_LEVEL 不变;同步 electron-log 文件 transport。 */
export function setLogLevel(level: LogLevel): void {
  if (!(level in LOG_LEVELS)) return; // 无效级别:忽略,保持 CURRENT_LEVEL 不变
  CURRENT_LEVEL = level;
  try {
    log.transports.file.level = level;
  } catch {
    /* electron-log transport 在测试/无 electron 环境可能未配置,忽略 */
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
