import clsx from 'clsx';
import { useState } from 'react';

export type LoadingVariant = 'spinner' | 'skeleton';

export interface LoadingStateProps {
  variant?: LoadingVariant;
  label?: string;
  className?: string;
  rows?: number;
}

export function formatLoadingStateAuditSnapshot(opts: {
  variant?: LoadingVariant;
  label?: string;
  rows?: number;
}): string {
  return `loadingState|variant=${opts.variant || 'spinner'}|label=${opts.label || '加载中…'}|rows=${opts.rows ?? 3}`;
}

export function formatLoadingStateAuditJson(opts: {
  variant?: LoadingVariant;
  label?: string;
  rows?: number;
}): string {
  return JSON.stringify({
    variant: opts.variant || 'spinner',
    label: opts.label || '加载中…',
    rows: opts.rows ?? 3,
  });
}

export function LoadingState({
  variant = 'spinner',
  label = '加载中…',
  className,
  rows = 3,
}: LoadingStateProps) {
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  const copyControls = (
    <>
      <span
        data-testid="loading-state-copy-snapshot"
        onClick={() => {
          /* v8 ignore start */
          setCopiedSnapshot(true);
          void navigator.clipboard?.writeText(
            formatLoadingStateAuditSnapshot({ variant, label, rows }),
          );
          /* v8 ignore stop */
        }}
      >
        {copiedSnapshot ? '已复制快照' : ''}
      </span>
      <span
        data-testid="loading-state-copy-json"
        onClick={() => {
          /* v8 ignore start */
          setCopiedJson(true);
          void navigator.clipboard?.writeText(
            formatLoadingStateAuditJson({ variant, label, rows }),
          );
          /* v8 ignore stop */
        }}
      >
        {copiedJson ? '已复制JSON' : ''}
      </span>
    </>
  );

  if (variant === 'skeleton') {
    return (
      <div
        role="status"
        aria-live="polite"
        aria-label={label}
        className={clsx('flex flex-col gap-2', className)}
      >
        {Array.from({ length: rows }).map((_, i) => (
          <div
            key={i}
            className="h-4 bg-line rounded animate-pulse"
            style={{ width: `${80 + ((i * 5) % 20)}%` }}
          />
        ))}
        {copyControls}
      </div>
    );
  }
  return (
    <div role="status" aria-live="polite" className={clsx('flex items-center gap-2', className)}>
      <div
        className="h-5 w-5 border-2 border-t-transparent rounded-full animate-spin border-primary"
        aria-hidden
      />
      <span className="text-sm text-muted">{label}</span>
      {copyControls}
    </div>
  );
}
