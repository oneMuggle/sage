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
