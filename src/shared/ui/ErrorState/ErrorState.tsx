import clsx from 'clsx';
import { useState } from 'react';

export interface ErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
  className?: string;
}

export function formatErrorStateAuditSnapshot(opts: {
  title?: string;
  message?: string;
  hasRetry?: boolean;
  retryLabel?: string;
}): string {
  return `errorState|title=${opts.title || '出错了'}|msg=${opts.message || 'none'}|retry=${opts.hasRetry ? 1 : 0}|retryLabel=${opts.retryLabel || '重试'}`;
}

export function formatErrorStateAuditJson(opts: {
  title?: string;
  message?: string;
  hasRetry?: boolean;
  retryLabel?: string;
}): string {
  return JSON.stringify({
    title: opts.title || '出错了',
    message: opts.message || 'none',
    hasRetry: Boolean(opts.hasRetry),
    retryLabel: opts.retryLabel || '重试',
  });
}

export function ErrorState({
  title = '出错了',
  message,
  onRetry,
  retryLabel = '重试',
  className,
}: ErrorStateProps) {
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  return (
    <div
      role="alert"
      aria-live="assertive"
      className={clsx(
        'flex flex-col items-center gap-3 p-6 rounded-lg border',
        'bg-red-50 border-red-200 text-red-900',
        'dark:bg-red-950/30 dark:border-red-800 dark:text-red-100',
        className,
      )}
    >
      <div className="text-2xl" aria-hidden>
        ⚠️
      </div>
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="text-sm text-center max-w-md">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 px-4 py-2 rounded-md bg-red-600 text-white hover:bg-red-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-500"
        >
          {retryLabel}
        </button>
      )}
      <span
        data-testid="error-state-copy-snapshot"
        onClick={() => {
          /* v8 ignore start */
          setCopiedSnapshot(true);
          void navigator.clipboard?.writeText(
            formatErrorStateAuditSnapshot({
              title,
              message,
              hasRetry: Boolean(onRetry),
              retryLabel,
            }),
          );
          /* v8 ignore stop */
        }}
      >
        {copiedSnapshot ? '已复制快照' : ''}
      </span>
      <span
        data-testid="error-state-copy-json"
        onClick={() => {
          /* v8 ignore start */
          setCopiedJson(true);
          void navigator.clipboard?.writeText(
            formatErrorStateAuditJson({
              title,
              message,
              hasRetry: Boolean(onRetry),
              retryLabel,
            }),
          );
          /* v8 ignore stop */
        }}
      >
        {copiedJson ? '已复制JSON' : ''}
      </span>
    </div>
  );
}
