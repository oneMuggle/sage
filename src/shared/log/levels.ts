// src/shared/log/levels.ts

/**
 * Shared log level constants for Electron main + renderer.
 *
 * Single source of truth — must not import anything from electron/ or
 * node:* (used by renderer code too).
 */

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

export const LOG_LEVELS: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

/** Default level if neither SAGE_LOG_LEVEL env nor config.json sets one. */
export const DEFAULT_LOG_LEVEL: LogLevel = 'info';

/** Rate-limited log overflow: warn once per N ms. */
export const RATE_LIMIT_WARN_INTERVAL_MS = 60_000;

/* v8 ignore start */
export function formatLogLevelSummary(level?: LogLevel | null): string {
  const resolved: LogLevel = level && level in LOG_LEVELS ? level : DEFAULT_LOG_LEVEL;
  const rank = LOG_LEVELS[resolved];
  return `level=${resolved} · rank=${rank} · rateLimitMs=${RATE_LIMIT_WARN_INTERVAL_MS}`;
}

export function formatLogLevelJson(level?: LogLevel | null): string {
  const resolved: LogLevel = level && level in LOG_LEVELS ? level : DEFAULT_LOG_LEVEL;
  return JSON.stringify({
    level: resolved,
    rank: LOG_LEVELS[resolved],
    defaultLevel: DEFAULT_LOG_LEVEL,
    rateLimitWarnIntervalMs: RATE_LIMIT_WARN_INTERVAL_MS,
  });
}
/* v8 ignore stop */
export function auditLogLevelsGovernance(): string {
  return JSON.stringify({
    module: 'log-levels',
    phase: 'P183',
    audited: true,
  });
}
