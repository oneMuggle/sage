import log from 'electron-log';

export function createLogger(scope: string) {
  return {
    debug: (message: string, ...args: any[]) => log.debug(`[${scope}] ${message}`, ...args),
    info: (message: string, ...args: any[]) => log.info(`[${scope}] ${message}`, ...args),
    warn: (message: string, ...args: any[]) => log.warn(`[${scope}] ${message}`, ...args),
    error: (message: string, ...args: any[]) => log.error(`[${scope}] ${message}`, ...args),
  };
}
