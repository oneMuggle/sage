// src/widgets/chat/RetryBanner.tsx
//
// 2026-10-20: LLM 重试可视化横幅。
//
// 后端 llm_client.py 在限流/超时/服务端错误/网络错误时按指数退避重试，
// 并通过 AgentEvent(state='retry', retry_info={...}) 推给前端。此前前端只把
// 重试信息写成一行纯文本塞进气泡，与正文无视觉区分，用户很难察觉系统在
// 自动恢复。本组件把重试过程渲染成独立横幅：旋转图标 + 次数 + 错误原因 +
// 剩余等待秒数 + 尝试进度点。
//
// 错误类型标签 / 倒计时单位走 i18n（src/shared/lib/i18n/retryBanner.ts），
// 严重程度配色在下方 RETRY_ERROR_META 单源映射 —— 错误类型与展示属性
// （标签 key + 严重等级）只在一处维护。

import { AlertCircle, Clock, RefreshCw } from 'lucide-react';

import type { RetryInfo } from '../../shared/api';
import type { TranslationKey } from '../../shared/lib/i18n';
import { useI18n } from '../../shared/lib/i18n';
import { useCountdown } from '../../shared/lib/useCountdown';

interface RetryBannerProps {
  /** 后端推送的重试信息（attempt/max_attempts/error_type/error_message/delay） */
  info: RetryInfo;
}

/** 严重程度 → 配色。 */
type Severity = 'warning' | 'error' | 'muted';

/**
 * 错误类型 → 展示属性（i18n key + 严重等级）。
 *
 * - warning：可自愈的瞬时故障（限流/超时/网络抖动），系统会自动恢复
 * - error：需要用户介入（认证失败/上下文溢出/解析失败/服务端持续错误）
 * - muted：未知类型，不误导用户
 *
 * 单源映射：错误类型 ↔ 展示属性只在此处维护，不再与 features/send-message
 * 的标签表重复。
 */
const RETRY_ERROR_META: Record<string, { labelKey: TranslationKey; severity: Severity }> = {
  timeout: { labelKey: 'chat.retry.error.timeout', severity: 'warning' },
  network_error: { labelKey: 'chat.retry.error.network_error', severity: 'warning' },
  rate_limited: { labelKey: 'chat.retry.error.rate_limited', severity: 'warning' },
  server_error: { labelKey: 'chat.retry.error.server_error', severity: 'error' },
  auth_failed: { labelKey: 'chat.retry.error.auth_failed', severity: 'error' },
  parsing_error: { labelKey: 'chat.retry.error.parsing_error', severity: 'error' },
  context_overflow: { labelKey: 'chat.retry.error.context_overflow', severity: 'error' },
  unknown: { labelKey: 'chat.retry.error.unknown', severity: 'muted' },
};

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
  const { t } = useI18n();
  const meta = RETRY_ERROR_META[info.error_type];
  const severity: Severity = meta?.severity ?? 'muted';
  const textClass = SEVERITY_TEXT[severity];
  // attempt 参与 resetKey —— 连续两次重试 delay 相同时倒计时也要归零重来
  const remaining = useCountdown(info.delay, info.attempt);
  // 标签取 i18n key；未知 error_type 直接透传（保留后端新增类型的可见性）
  const reason = meta ? t(meta.labelKey) : info.error_type;
  const attemptCount = Math.max(info.max_attempts, 1);
  const title = t('chat.retry.in_progress')
    .replace('{attempt}', String(info.attempt))
    .replace('{max}', String(info.max_attempts));

  return (
    <div
      data-testid="retry-banner"
      role="status"
      aria-live="polite"
      className={`flex items-center gap-2 px-3 py-1.5 my-2 rounded-radius-sm border text-xs ${SEVERITY_BG[severity]}`}
    >
      <RefreshCw className={`w-3.5 h-3.5 flex-shrink-0 animate-spin ${textClass}`} />
      <span className={`font-medium flex-shrink-0 ${textClass}`}>{title}</span>

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
          aria-hidden="true"
          className="flex items-center gap-1 flex-shrink-0 text-text-secondary"
          data-testid="retry-banner-countdown"
        >
          <Clock className="w-3 h-3" aria-hidden="true" />
          <span className="font-mono tabular-nums">
            {t('chat.retry.seconds').replace('{seconds}', String(remaining))}
          </span>
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
export function formatRetryBannerSummary(info: RetryInfo): string {
  const severity: Severity = RETRY_ERROR_META[info.error_type]?.severity ?? 'muted';
  return `attempt=${info.attempt}/${info.max_attempts} · type=${info.error_type} · severity=${severity} · delay=${info.delay}s`;
}

export function formatRetryBannerJson(info: RetryInfo): string {
  const severity: Severity = RETRY_ERROR_META[info.error_type]?.severity ?? 'muted';
  return JSON.stringify(
    {
      attempt: info.attempt,
      maxAttempts: info.max_attempts,
      errorType: info.error_type,
      severity,
      delay: info.delay,
    },
    null,
    2,
  );
}
