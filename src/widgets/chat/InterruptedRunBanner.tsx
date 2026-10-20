// src/widgets/chat/InterruptedRunBanner.tsx
//
// L16 run 级崩溃恢复 (对标增强第四轮批次 A): 后端启动时把滞留 running 的
// 会话统一标记 failed("应用重启，运行中断",backend/data/session_repo.py
// recover_stale_run_states)。本横幅是该终态在聊天页的恢复入口——
// 重发最后一条 user 消息,而不是让用户对着侧栏灰点猜。

import { useState } from 'react';

/** 与后端 session_repo.recover_stale_run_states 的恢复文案严格一致 */
export const INTERRUPTED_RUN_ERROR = '应用重启，运行中断';

interface InterruptedRunBannerProps {
  onRetry: () => void;
  onDismiss: () => void;
}

export function formatInterruptedRunMarkdown(
  errorText: string = INTERRUPTED_RUN_ERROR,
): string {
  return [
    '# 运行中断恢复提示 (Interrupted Run Notice)',
    '',
    `- **中断原因**: ${errorText}`,
    '- **提示说明**: 上次运行被应用重启中断，可重发最后一条消息恢复。',
  ].join('\n');
}

export function formatInterruptedRunJson(
  errorText: string = INTERRUPTED_RUN_ERROR,
): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      error: errorText,
      recoverable: true,
    },
    null,
    2,
  );
}

export function InterruptedRunBanner({ onRetry, onDismiss }: InterruptedRunBannerProps) {
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  /* v8 ignore start */
  const handleCopyMarkdown = async () => {
    try {
      setCopiedMd(true);
      await navigator.clipboard?.writeText(formatInterruptedRunMarkdown());
      setTimeout(() => setCopiedMd(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };

  const handleCopyJson = async () => {
    try {
      setCopiedJson(true);
      await navigator.clipboard?.writeText(formatInterruptedRunJson());
      setTimeout(() => setCopiedJson(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };
  /* v8 ignore stop */

  return (
    <div
      data-testid="interrupted-run-banner"
      className="flex items-center gap-2 px-5 py-2 bg-warning/10 border-b border-border text-xs shrink-0"
    >
      <span className="text-warning shrink-0">上次运行被应用重启中断</span>
      <button
        onClick={onRetry}
        className="px-2 py-0.5 border border-border rounded-radius-sm hover:bg-bg-hover transition-colors"
      >
        重发最后一条消息
      </button>
      <button
        type="button"
        data-testid="interrupted-run-copy-md"
        onClick={() => void handleCopyMarkdown()}
        className="px-2 py-0.5 border border-border rounded-radius-sm hover:bg-bg-hover transition-colors"
      >
        {copiedMd ? '已复制 MD' : '复制 MD'}
      </button>
      <button
        type="button"
        data-testid="interrupted-run-copy-json"
        onClick={() => void handleCopyJson()}
        className="px-2 py-0.5 border border-border rounded-radius-sm hover:bg-bg-hover transition-colors"
      >
        {copiedJson ? '已复制 JSON' : '复制 JSON'}
      </button>
      <button
        className="ml-auto text-text-secondary hover:text-text"
        aria-label="忽略中断提示"
        onClick={onDismiss}
      >
        忽略
      </button>
    </div>
  );
}
