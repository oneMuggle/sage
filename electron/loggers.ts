import log from 'electron-log';

export function createLogger(scope: string) {
  return {
    debug: (message: string, ...args: unknown[]) => log.debug(`[${scope}] ${message}`, ...args),
    info: (message: string, ...args: unknown[]) => log.info(`[${scope}] ${message}`, ...args),
    warn: (message: string, ...args: unknown[]) => log.warn(`[${scope}] ${message}`, ...args),
    error: (message: string, ...args: unknown[]) => log.error(`[${scope}] ${message}`, ...args),
  };
}
