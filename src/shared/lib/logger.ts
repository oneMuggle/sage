/**
 * 轻量结构化 logger，支持 request_id 追踪
 * 用于诊断 LLM 链路 Bug
 */

type LogLevel = 'debug' | 'info' | 'warn' | 'error';

class Logger {
  private enabled = false;

  setEnabled(value: boolean): void {
    this.enabled = value;
  }

  isEnabled(): boolean {
    return this.enabled;
  }

  private log(level: LogLevel, requestId: string, label: string, data?: unknown): void {
    if (!this.enabled) return;
    const prefix = `[${requestId}] [${label}]`;
    // eslint-disable-next-line no-console
    const consoleFn = console[level] as (...args: unknown[]) => void;
    if (data instanceof Error) {
      consoleFn(prefix, data.message, data.stack);
    } else if (data !== undefined) {
      consoleFn(prefix, data);
    } else {
      consoleFn(prefix);
    }
  }

  debug(requestId: string, label: string, data?: unknown): void {
    this.log('debug', requestId, label, data);
  }

  info(requestId: string, label: string, data?: unknown): void {
    this.log('info', requestId, label, data);
  }

  warn(requestId: string, label: string, data?: unknown): void {
    this.log('warn', requestId, label, data);
  }

  error(requestId: string, label: string, data?: unknown): void {
    this.log('error', requestId, label, data);
  }
}

export const logger = new Logger();

// 开发模式默认开启；生产模式默认关闭
if (import.meta.env.DEV) {
  logger.setEnabled(true);
}

/* v8 ignore start */
export function formatLoggerAuditSummary(enabled?: boolean | null): string {
  const active = typeof enabled === 'boolean' ? enabled : logger.isEnabled();
  return `logger=${active ? 'enabled' : 'disabled'}`;
}

export function formatLoggerAuditJson(enabled?: boolean | null): string {
  const active = typeof enabled === 'boolean' ? enabled : logger.isEnabled();
  return JSON.stringify({
    enabled: active,
  });
}
/* v8 ignore stop */

export function auditLoggerGovernance(): string {
  return JSON.stringify(
    {
      schema: 'sage.shared.lib.logger.governance.v1',
      phase: 'P179',
      levels: ['debug', 'info', 'warn', 'error'],
      sampleSummary: formatLoggerAuditSummary(true),
    },
    null,
    2,
  );
}
