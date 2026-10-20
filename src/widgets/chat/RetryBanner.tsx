// src/widgets/chat/RetryBanner.tsx
//
// 2026-10-20: LLM 重试可视化横幅。
//
// 后端 llm_client.py 在限流/超时/服务端错误/网络错误时按指数退避重试，
// 并通过 AgentEvent(state='retry', retry_info={...}) 推给前端。此前前端只把
// 重试信息写成一行纯文本塞进气泡，与正文无视觉区分，用户很难察觉系统在
// 自动恢复。本组件把重试过程渲染成独立横幅：旋转图标 + 次数 + 错误原因 +
// 剩余等待秒数 + 尝试进度点。

import { AlertCircle, Clock, RefreshCw } from 'lucide-react';

import { retryErrorLabel } from '../../features/send-message/retryEventText';
import type { RetryInfo } from '../../shared/api';
import { useCountdown } from '../../shared/lib/useCountdown';

interface RetryBannerProps {
  /** 后端推送的重试信息（attempt/max_attempts/error_type/error_message/delay） */
  info: RetryInfo;
}

/** 严重程度 → 配色。 */
type Severity = 'warning' | 'error' | 'muted';

/**
 * 错误类型 → 严重程度。
 *
 * - warning：可自愈的瞬时故障（限流/超时/网络抖动），系统会自动恢复
 * - error：需要用户介入（认证失败/上下文溢出/服务端持续错误）
 * - muted：未知类型，不误导用户
 */
function severityOf(errorType: string): Severity {
  switch (errorType) {
    case 'rate_limited':
    case 'timeout':
    case 'network_error':
      return 'warning';
    case 'server_error':
    case 'auth_failed':
    case 'context_overflow':
    case 'parsing_error':
      return 'error';
    default:
      return 'muted';
  }
}

const SEVERITY_TEXT: Record<Severity, string> = {
  warning: 'text-warning',
  error: 'text-error',
  muted: 'text-muted',
};

const SEVERITY_BG: Record<Severity, string> = {
  warning: 'bg-warning/10 border-warning/30',
  error: 'bg-error/10 border-error/30',
  muted: 'bg-bg-subtle border-border',
};

const SEVERITY_DOT: Record<Severity, string> = {
  warning: 'bg-warning',
  error: 'bg-error',
  muted: 'bg-muted',
};

export function RetryBanner({ info }: RetryBannerProps) {
  const severity = severityOf(info.error_type);
  const textClass = SEVERITY_TEXT[severity];
  // attempt 参与 resetKey —— 连续两次重试 delay 相同时倒计时也要归零重来
  const remaining = useCountdown(info.delay, info.attempt);
  const reason = retryErrorLabel(info.error_type);
  const attemptCount = Math.max(info.max_attempts, 1);

  return (
    <div
      data-testid="retry-banner"
      role="status"
      aria-live="polite"
      className={`flex items-center gap-2 px-3 py-1.5 my-2 rounded-radius-sm border text-xs ${SEVERITY_BG[severity]}`}
    >
      <RefreshCw className={`w-3.5 h-3.5 flex-shrink-0 animate-spin ${textClass}`} />
      <span className={`font-medium flex-shrink-0 ${textClass}`}>
        重试中 ({info.attempt}/{info.max_attempts})
      </span>

      <span
        className="flex items-center gap-1 min-w-0"
        title={info.error_message || reason}
        data-testid="retry-banner-reason"
      >
        <AlertCircle className={`w-3 h-3 flex-shrink-0 ${textClass}`} />
        <span className="truncate text-text-secondary">{reason}</span>
      </span>

      {remaining > 0 && (
        <span
          className="flex items-center gap-1 flex-shrink-0 text-text-secondary"
          data-testid="retry-banner-countdown"
        >
          <Clock className="w-3 h-3" />
          <span className="font-mono tabular-nums">{remaining}s</span>
        </span>
      )}

      {/* 尝试进度点：已完成的 attempt 个实心，其余空心 */}
      <span className="flex items-center gap-0.5 ml-auto flex-shrink-0" aria-hidden="true">
        {Array.from({ length: attemptCount }, (_, i) => (
          <span
            key={i}
            className={`w-1.5 h-1.5 rounded-full ${i < info.attempt ? SEVERITY_DOT[severity] : 'bg-border'}`}
          />
        ))}
      </span>
    </div>
  );
}
