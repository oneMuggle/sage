import { useState } from 'react';
import clsx from 'clsx';

export interface RetryButtonProps {
  onRetry: () => void | Promise<void>;
  maxAttempts?: number;
  backoffMs?: readonly number[];
  label?: string;
  className?: string;
}

const DEFAULT_BACKOFF = [1000, 2000, 4000] as const;

export function RetryButton({
  onRetry,
  maxAttempts = 3,
  backoffMs = DEFAULT_BACKOFF,
  label = '重试',
  className,
}: RetryButtonProps) {
  const [attempts, setAttempts] = useState(0);
  const [busy, setBusy] = useState(false);

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
  );
}
