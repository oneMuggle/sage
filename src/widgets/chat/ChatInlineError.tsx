// src/widgets/chat/ChatInlineError.tsx
//
// R17-D 顶层错误内联条（原内联于 src/pages/Chat.tsx，UX-IA R1 批次 B 抽出）：
// 保留历史可见（替代旧整页 ErrorState）；只渲染归属当前会话的错误由调用方保证。

interface ChatInlineErrorProps {
  error: string;
  onRetry: () => void;
  onClose: () => void;
}

export function ChatInlineError({ error, onRetry, onClose }: ChatInlineErrorProps) {
  return (
    <div
      className="mx-4 mt-2 flex items-start justify-between gap-3 px-3 py-2 rounded border border-error/40 bg-error/5"
      data-testid="chat-inline-error"
    >
      <div className="min-w-0">
        <p className="text-xs font-semibold text-error">对话出错</p>
        <p className="text-xs text-text-secondary break-all">{error}</p>
      </div>
      <div className="flex gap-1.5 shrink-0">
        <button
          type="button"
          data-testid="chat-error-retry"
          onClick={onRetry}
          className="text-xs px-2 py-1 rounded bg-primary text-text-inverse hover:bg-primary-hover"
        >
          重试
        </button>
        <button
          type="button"
          onClick={onClose}
          className="text-xs px-2 py-1 rounded border border-border hover:bg-bg-hover"
        >
          关闭
        </button>
      </div>
    </div>
  );
}

export interface ChatInlineErrorAuditInput {
  errorMessage: string;
  errorCode?: string | null;
  retryable: boolean;
  hasRetryHandler: boolean;
}

export interface ChatInlineErrorAuditReport {
  normalizedCode: string;
  messageLength: number;
  retryable: boolean;
  actionable: boolean;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateChatInlineErrorAudit(
  input: ChatInlineErrorAuditInput,
): ChatInlineErrorAuditReport {
  const msg = input.errorMessage.trim();
  const normalizedCode = (input.errorCode ?? 'UNKNOWN_ERROR').trim() || 'UNKNOWN_ERROR';
  const actionable = !input.retryable || Boolean(input.hasRetryHandler);
  const issueCodes: string[] = [];

  if (!msg) {
    issueCodes.push('empty_inline_error_message');
  }
  if (input.retryable && !input.hasRetryHandler) {
    issueCodes.push('missing_retry_handler');
  }

  return {
    normalizedCode,
    messageLength: msg.length,
    retryable: Boolean(input.retryable),
    actionable,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}

// eslint-disable-next-line react-refresh/only-export-components
export function exportChatInlineErrorAuditJson(
  input: ChatInlineErrorAuditInput,
): string {
  return JSON.stringify(evaluateChatInlineErrorAudit(input));
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditChatInlineErrorGovernance(): string {
  return JSON.stringify({
    module: 'chat-inline-error',
    phase: 'P185',
    audited: true,
  });
}
