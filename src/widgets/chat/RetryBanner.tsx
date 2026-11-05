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
// 2026-11-03: 重试阶段双态 —— 退避等待（backoff）与在途请求（in_flight）。
// 后端在退避结束后推送 retry_attempt_started 事件把 phase 切换到 in_flight，
// 此时没有可倒数的目标（等上游响应），只知道已经等了多久。横幅据此
// 切换副标题与计时字段：backoff 显示"将在 N 秒后重试 + 累计已等待"，
// in_flight 显示"重试请求已发出 + 本次已等待 + 单次上限 + 剩余预算"。
// 与 Claude Code 的 "Retrying in Ns · attempt x/y" 行为对齐。
//
// 后端推送的 elapsed_s / budget_remaining_s 是事件时刻的快照，本身静止；
// 横幅叠加本地计时（useElapsed），让"已等待"随时间推进而非卡住不动。
//
// 错误类型标签 / 倒计时单位走 i18n（src/shared/lib/i18n/retryBanner.ts），
// 严重程度配色在下方 RETRY_ERROR_META 单源映射 —— 错误类型与展示属性
// （标签 key + 严重等级）只在一处维护。

import { AlertCircle, Clock, Loader2, RefreshCw } from 'lucide-react';

import type { RetryInfo } from '../../shared/api';
import type { TranslationKey } from '../../shared/lib/i18n';
import { useI18n } from '../../shared/lib/i18n';
import { useCountdown, useElapsed } from '../../shared/lib/useCountdown';

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
  // 2026-11-03: in_flight 阶段的"本次已等待"计数器 —— 以 attempt 为重置键,
  // phase 也参与 key 以避免 backoff→in_flight 切换时显示错误的累积值。
  const attemptElapsed = useElapsed(`${info.attempt}-${info.phase ?? 'backoff'}`);
  // 标签取 i18n key；未知 error_type 直接透传（保留后端新增类型的可见性）
  const reason = meta ? t(meta.labelKey) : info.error_type;
  const attemptCount = Math.max(info.max_attempts, 1);
  const phase: 'backoff' | 'in_flight' = info.phase === 'in_flight' ? 'in_flight' : 'backoff';
  // 标题：两阶段共用"重试中 (x/y)"，阶段差异由副标题与图标承载
  const title = t('chat.retry.in_progress')
    .replace('{attempt}', String(info.attempt))
    .replace('{max}', String(info.max_attempts));
  // 副标题：退避期显示倒计时 + 恢复提示；在途期显示等待提示
  const subtitle =
    phase === 'in_flight'
      ? t('chat.retry.in_flight_hint')
      : remaining > 0
        ? t('chat.retry.backoff_hint').replace('{seconds}', String(remaining))
        : null;
  // 来源提示（如 compaction = 会话压缩触发的后台调用）
  const sourceLabel = info.source === 'compaction' ? t('chat.retry.source.compaction') : null;
  // 累计已等待 = 后端快照（事件时刻）+ 本地已流逝秒数。快照本身会静止，
  // 叠加本地计时后数字才真正"在走"，用户才能判断系统没卡死。
  const liveElapsed = info.elapsed_s != null ? info.elapsed_s + attemptElapsed : null;

  return (
    <div
      data-testid="retry-banner"
      data-phase={phase}
      role="status"
      aria-live="polite"
      className={`flex flex-wrap items-center gap-2 px-3 py-1.5 my-2 rounded-radius-sm border text-xs ${SEVERITY_BG[severity]}`}
    >
      {/* 图标：in_flight 用 Loader2（持续旋转，暗示"请求在途"）；backoff 沿用 RefreshCw */}
      {phase === 'in_flight' ? (
        <Loader2 className={`w-3.5 h-3.5 flex-shrink-0 animate-spin ${textClass}`} />
      ) : (
        <RefreshCw className={`w-3.5 h-3.5 flex-shrink-0 animate-spin ${textClass}`} />
      )}
      <span className={`font-medium flex-shrink-0 ${textClass}`}>{title}</span>

      {subtitle && (
        <span className="text-text-secondary" data-testid="retry-banner-subtitle">
          {subtitle}
        </span>
      )}

      <span
        className="flex items-center gap-1 min-w-0"
        title={info.error_message || reason}
        data-testid="retry-banner-reason"
      >
        <AlertCircle className={`w-3 h-3 flex-shrink-0 ${textClass}`} />
        <span className="truncate text-text-secondary">{reason}</span>
      </span>

      {sourceLabel && (
        <span className="text-text-secondary italic" data-testid="retry-banner-source">
          {sourceLabel}
        </span>
      )}

      {/* 累计已等待：后端推送 elapsed_s 时展示（含退避 + 在途），随本地计时推进 */}
      {liveElapsed != null && liveElapsed >= 1 && (
        <span
          aria-hidden="true"
          className="flex items-center gap-1 flex-shrink-0 text-text-secondary"
          data-testid="retry-banner-elapsed"
        >
          <Clock className="w-3 h-3" aria-hidden="true" />
          <span className="font-mono tabular-nums">
            {t('chat.retry.elapsed').replace('{seconds}', String(Math.round(liveElapsed)))}
          </span>
        </span>
      )}

      {/* in_flight 阶段：本次已等待 + 单次上限 */}
      {phase === 'in_flight' && (
        <span
          className="flex items-center gap-1 flex-shrink-0 text-text-secondary"
          data-testid="retry-banner-attempt-elapsed"
        >
          <Clock className="w-3 h-3" aria-hidden="true" />
          <span className="font-mono tabular-nums">
            {t('chat.retry.attempt_elapsed').replace('{seconds}', String(attemptElapsed))}
          </span>
        </span>
      )}
      {phase === 'in_flight' && info.attempt_timeout_s != null && (
        <span
          className="flex items-center gap-1 flex-shrink-0 text-text-secondary"
          data-testid="retry-banner-attempt-timeout"
        >
          <Clock className="w-3 h-3" aria-hidden="true" />
          <span className="font-mono tabular-nums">
            {t('chat.retry.attempt_timeout').replace(
              '{seconds}',
              String(Math.round(info.attempt_timeout_s)),
            )}
          </span>
        </span>
      )}

      {/* 退避期：保留原 countdown 显示（仅当 remaining > 0） */}
      {phase === 'backoff' && remaining > 0 && (
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

      {/* 2026-11-02: 总时长预算可见性 — 后端推送 budget_remaining_s 时展示 */}
      {info.budget_total_s != null && info.budget_remaining_s != null && (
        <span
          className="flex items-center gap-1 flex-shrink-0 text-text-secondary"
          data-testid="retry-banner-budget"
        >
          <Clock className="w-3 h-3" aria-hidden="true" />
          <span className="font-mono tabular-nums">
            {t('chat.retry.budget_remaining').replace(
              '{seconds}',
              String(Math.max(0, Math.round(info.budget_remaining_s))),
            )}
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
  const phase = info.phase === 'in_flight' ? 'in_flight' : 'backoff';
  const parts = [
    `attempt=${info.attempt}/${info.max_attempts}`,
    `type=${info.error_type}`,
    `severity=${severity}`,
    `delay=${info.delay}s`,
    `phase=${phase}`,
  ];
  if (info.elapsed_s != null) parts.push(`elapsed=${info.elapsed_s}s`);
  if (info.attempt_timeout_s != null) parts.push(`timeout=${info.attempt_timeout_s}s`);
  if (info.budget_remaining_s != null) parts.push(`budget=${info.budget_remaining_s}s`);
  return parts.join(' · ');
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
      phase: info.phase === 'in_flight' ? 'in_flight' : 'backoff',
      elapsedS: info.elapsed_s ?? null,
      attemptTimeoutS: info.attempt_timeout_s ?? null,
      budgetTotalS: info.budget_total_s ?? null,
      budgetRemainingS: info.budget_remaining_s ?? null,
      source: info.source ?? null,
    },
    null,
    2,
  );
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditRetryBannerGovernance(): string {
  return JSON.stringify({
    module: 'retry-banner',
    phase: 'P194',
    audited: true,
  });
}
