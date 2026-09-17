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

// 日志时区 (2026-09-17): 用户可选择日志时间戳使用的时区.
// 'UTC' = 使用 UTC 时间 (历史默认), 'local' = 使用系统本地时区, 其他 IANA 字符串.
// 默认 'UTC' 保持向后兼容; 由 Electron main 进程在读取 settings 后调用
// setLogTimezone() 更新此值.
let CURRENT_LOG_TIMEZONE: string = process.env.SAGE_LOG_TIMEZONE || 'UTC';

try {
  mkdirSync(LOG_DIR, { recursive: true });
  log.transports.file.resolvePath = () => join(LOG_DIR, 'electron-log-fallback.log');
  log.transports.file.level = CURRENT_LEVEL;
  log.transports.console.level = process.env.NODE_ENV === 'production' ? 'warn' : 'debug';
} catch (err) {
  console.error('[logger] failed to configure transports:', err);
}

/**
 * 将 Date 对象按当前 logTimezone 设置格式化为 ISO 字符串.
 * - 'UTC' → toISOString() (末尾带 'Z')
 * - 'local' → 本地时区的 ISO-like 字符串
 * - 其他 (IANA 时区) → 通过 Intl.DateTimeFormat 转换到该时区
 */
function formatTimestamp(date: Date, tz: string): string {
  if (tz === 'UTC') {
    return date.toISOString();
  }
  if (tz === 'local') {
    // 本地时区: 与 UTC 等价的可读格式, 含本机偏移.
    const pad = (n: number, w = 2) => String(n).padStart(w, '0');
    const y = date.getFullYear();
    const mo = pad(date.getMonth() + 1);
    const d = pad(date.getDate());
    const h = pad(date.getHours());
    const mi = pad(date.getMinutes());
    const s = pad(date.getSeconds());
    const ms = pad(date.getMilliseconds(), 3);
    const offset = -date.getTimezoneOffset(); // 分钟; 东八区为 +480
    const sign = offset >= 0 ? '+' : '-';
    const oh = pad(Math.floor(Math.abs(offset) / 60));
    const om = pad(Math.abs(offset) % 60);
    return `${y}-${mo}-${d}T${h}:${mi}:${s}.${ms}${sign}${oh}:${om}`;
  }
  // IANA 时区: 使用 Intl.DateTimeFormat 转换.
  try {
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: tz,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
      fractionalSecondDigits: 3,
    }).formatToParts(date);
    const get = (t: string) => parts.find((p) => p.type === t)?.value ?? '00';
    const y = get('year');
    const mo = get('month');
    const d = get('day');
    const h = get('hour') === '24' ? '00' : get('hour');
    const mi = get('minute');
    const s = get('second');
    const ms = get('fractionalSecond');
    // 计算该时区与 UTC 的偏移.
    const tzDate = new Date(date.toLocaleString('en-US', { timeZone: tz }));
    const offsetMin = (tzDate.getTime() - date.getTime()) / 60000 + date.getTimezoneOffset();
    const sign = offsetMin >= 0 ? '+' : '-';
    const oh = String(Math.floor(Math.abs(offsetMin) / 60)).padStart(2, '0');
    const om = String(Math.abs(offsetMin) % 60).padStart(2, '0');
    return `${y}-${mo}-${d}T${h}:${mi}:${s}.${ms}${sign}${oh}:${om}`;
  } catch {
    // 非法 IANA 时区 → 回落到 UTC.
    return date.toISOString();
  }
}

/** YYYY-MM-DD 提取 (按 logTimezone 切分文件). */
function formatDateOnly(date: Date, tz: string): string {
  if (tz === 'UTC') {
    return date.toISOString().slice(0, 10);
  }
  // local 或 IANA: 提取 YYYY-MM-DD 部分.
  return formatTimestamp(date, tz).slice(0, 10);
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
  const now = new Date();
  const line: Record<string, unknown> = {
    ts: formatTimestamp(now, CURRENT_LOG_TIMEZONE),
    level,
    source,
    msg,
  };
  if (meta !== undefined) {
    line.meta = safeStringify(meta);
  }
  const today = formatDateOnly(now, CURRENT_LOG_TIMEZONE);
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

/** 运行时切换日志时区 (2026-09-17). 接受 'UTC' | 'local' | IANA 时区字符串. 无效值忽略. */
export function setLogTimezone(tz: string): void {
  if (!tz || typeof tz !== 'string') return;
  // 'UTC' 和 'local' 是保留关键字; 其他视作 IANA 时区.
  // IANA 时区校验交给 formatTimestamp 的 try/catch 兜底.
  CURRENT_LOG_TIMEZONE = tz;
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
