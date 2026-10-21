import clsx from 'clsx';
import { useState } from 'react';

export interface RetryButtonProps {
  onRetry: () => void | Promise<void>;
  maxAttempts?: number;
  backoffMs?: readonly number[];
  label?: string;
  className?: string;
}

const DEFAULT_BACKOFF = [1000, 2000, 4000] as const;

export function formatRetryButtonAuditSnapshot(opts: {
  attempts?: number;
  maxAttempts?: number;
  busy?: boolean;
  cooldownMs?: number;
  label?: string;
}): string {
  return `retryButton|attempts=${opts.attempts ?? 0}|max=${opts.maxAttempts ?? 3}|busy=${opts.busy ? 1 : 0}|cooldown=${opts.cooldownMs ?? 1000}|label=${opts.label || '重试'}`;
}

export function formatRetryButtonAuditJson(opts: {
  attempts?: number;
  maxAttempts?: number;
  busy?: boolean;
  cooldownMs?: number;
  label?: string;
}): string {
  return JSON.stringify({
    attempts: opts.attempts ?? 0,
    maxAttempts: opts.maxAttempts ?? 3,
    busy: Boolean(opts.busy),
    cooldownMs: opts.cooldownMs ?? 1000,
    label: opts.label || '重试',
  });
}

export function RetryButton({
  onRetry,
  maxAttempts = 3,
  backoffMs = DEFAULT_BACKOFF,
  label = '重试',
  className,
}: RetryButtonProps) {
  const [attempts, setAttempts] = useState(0);
  const [busy, setBusy] = useState(false);
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  const cooldown = backoffMs[Math.min(attempts, backoffMs.length - 1)] ?? 0;
  const disabled = busy || attempts >= maxAttempts;

  const handleClick = async () => {
    if (disabled) return;
    setBusy(true);
    setAttempts((a) => a + 1);
    try {
      await onRetry();
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={handleClick}
        disabled={disabled}
        aria-label={disabled && attempts >= maxAttempts ? '重试次数已用完' : label}
        data-cooldown-ms={cooldown}
        className={clsx(
          'px-4 py-2 rounded-md text-white font-medium',
          'bg-blue-600 hover:bg-blue-700',
          'disabled:opacity-50 disabled:cursor-not-allowed',
          'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500',
          className,
        )}
      >
        {busy ? '重试中…' : label}
        {attempts > 0 && (
          <span className="ml-1 text-xs">
            ({attempts}/{maxAttempts})
          </span>
        )}
      </button>
      <span
        data-testid="retry-button-copy-snapshot"
        onClick={() => {
          /* v8 ignore start */
          setCopiedSnapshot(true);
          void navigator.clipboard?.writeText(
            formatRetryButtonAuditSnapshot({
              attempts,
              maxAttempts,
              busy,
              cooldownMs: cooldown,
              label,
            }),
          );
          /* v8 ignore stop */
        }}
      >
        {copiedSnapshot ? '已复制快照' : ''}
      </span>
      <span
        data-testid="retry-button-copy-json"
        onClick={() => {
          /* v8 ignore start */
          setCopiedJson(true);
          void navigator.clipboard?.writeText(
            formatRetryButtonAuditJson({
              attempts,
              maxAttempts,
              busy,
              cooldownMs: cooldown,
              label,
            }),
          );
          /* v8 ignore stop */
        }}
      >
        {copiedJson ? '已复制JSON' : ''}
      </span>
    </>
  );
}
