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
