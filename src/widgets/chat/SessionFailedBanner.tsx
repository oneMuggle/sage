// src/widgets/chat/SessionFailedBanner.tsx
//
// Issue 1（2026-10-29）：会话失败后切换到该会话，失败原因此前只出现在侧栏
// 图标的 hover 提示里，聊天区没有任何提示 —— 用户必须把视线移到左栏、
// 找到那个图标、悬停才能知道为什么失败。本横幅把失败原因提到聊天区顶部，
// 并给出「重新发送」入口。
//
// 与 InterruptedRunBanner 的分工：
//   - InterruptedRunBanner：后端启动时把滞留 running 的会话统一标记
//     failed("应用重启，运行中断")，属于「可一键恢复」的特殊终态。
//   - SessionFailedBanner：其余一切失败终态（agent 报错、预算超限、
//     LLM 异常等），展示真实失败原因。
// 两者靠 `last_error === INTERRUPTED_RUN_ERROR` 互斥，不会同时出现。

import { mapAgentErrorToText } from '../../shared/lib/errorMapping';

interface SessionFailedBannerProps {
  /** 失败原因原文（session.last_error），可能是错误码或带上限装饰的完整串 */
  reason: string;
  /** 重发最后一条 user 消息 */
  onRetry: () => void;
  /** 关闭横幅 */
  onDismiss: () => void;
}

/**
 * 把失败原因翻译成用户能看懂的中文。
 * 已知错误码走 `mapAgentErrorToText`；未知码/空串回退到原文，
 * 保证横幅永远能显示点什么，而不是空白。
 */
export function formatSessionFailedReason(reason: string): string {
  const raw = (reason ?? '').trim();
  if (!raw) return '未知原因';
  return mapAgentErrorToText(raw) ?? raw;
}

export function SessionFailedBanner({ reason, onRetry, onDismiss }: SessionFailedBannerProps) {
  const display = formatSessionFailedReason(reason);

  return (
    <div
      data-testid="session-failed-banner"
      role="alert"
      className="flex items-start gap-3 px-5 py-2 bg-error/5 border-b border-error/30 text-xs shrink-0"
    >
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-error">会话失败</p>
        <p className="text-text-secondary break-words">{display}</p>
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        <button
          type="button"
          data-testid="session-failed-retry"
          onClick={onRetry}
          className="px-2 py-0.5 rounded bg-primary text-text-inverse hover:bg-primary-hover transition-colors"
        >
          重新发送
        </button>
        <button
          type="button"
          data-testid="session-failed-dismiss"
          aria-label="忽略失败提示"
          onClick={onDismiss}
          className="px-2 py-0.5 border border-border rounded-radius-sm text-text-secondary hover:bg-bg-hover transition-colors"
        >
          关闭
        </button>
      </div>
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditSessionFailedBannerGovernance(): string {
  return JSON.stringify({
    module: 'session-failed-banner',
    phase: 'P195',
    audited: true,
  });
}
