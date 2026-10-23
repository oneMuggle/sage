export function createLogger(scope: string) {
  return {
    // eslint-disable-next-line no-console
    debug: (message: string, ...args: unknown[]) => console.debug(`[${scope}] ${message}`, ...args),
    // eslint-disable-next-line no-console
    info: (message: string, ...args: unknown[]) => console.info(`[${scope}] ${message}`, ...args),
    warn: (message: string, ...args: unknown[]) => console.warn(`[${scope}] ${message}`, ...args),
    error: (message: string, ...args: unknown[]) => console.error(`[${scope}] ${message}`, ...args),
  };
}

export function formatLoggerEntrySummary(
  scope: string,
  level: 'debug' | 'info' | 'warn' | 'error',
  message: string,
): string {
  return `[${scope}] ${level.toUpperCase()} · ${message}`;
}

export function formatLoggerEntryJson(
  scope: string,
  level: 'debug' | 'info' | 'warn' | 'error',
  message: string,
): string {
  return JSON.stringify(
    {
      scope,
      level,
      message,
    },
    null,
    2,
  );
}

export function auditLoggerGovernance(): {
  module: 'src/shared/logger.ts';
  phase: 'P174';
  domain: 'shared';
  levels: readonly ['debug', 'info', 'warn', 'error'];
  compliant: boolean;
} {
  const summary = formatLoggerEntrySummary('governance', 'info', 'ready');
  return {
    module: 'src/shared/logger.ts',
    phase: 'P174',
    domain: 'shared',
    levels: ['debug', 'info', 'warn', 'error'],
    compliant: summary.includes('[governance] INFO'),
  };
}
