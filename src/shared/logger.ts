export function createLogger(scope: string) {
  return {
    debug: (message: string, ...args: any[]) => console.debug(`[${scope}] ${message}`, ...args),
    info: (message: string, ...args: any[]) => console.info(`[${scope}] ${message}`, ...args),
    warn: (message: string, ...args: any[]) => console.warn(`[${scope}] ${message}`, ...args),
    error: (message: string, ...args: any[]) => console.error(`[${scope}] ${message}`, ...args),
  };
}
