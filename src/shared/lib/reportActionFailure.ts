import { toast } from 'sonner';

export interface ReportActionFailureOptions {
  /** Fallback text when error carries no message. */
  fallback?: string;
  /** Whether to trigger a user-visible error toast (defaults to true). */
  notify?: boolean;
}

export function formatActionError(error: unknown, fallback = '操作失败'): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message.trim();
  }
  if (typeof error === 'string' && error.trim()) {
    return error.trim();
  }
  return fallback;
}

/**
 * U4: Unified helper for non-silent error reporting on user-triggered actions
 * and capability probes. Extracts a readable message, logs a structured warning,
 * and optionally surfaces a Sonner error toast.
 */
export function reportActionFailure(
  context: string,
  error: unknown,
  options: ReportActionFailureOptions = {},
): string {
  const detail = formatActionError(error, options.fallback);
  const message = `${context}：${detail}`;
  console.warn(`[ActionFailure] ${message}`, error);
  if (options.notify !== false) {
    toast.error(message);
  }
  return message;
}
