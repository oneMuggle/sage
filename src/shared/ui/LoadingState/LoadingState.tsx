import clsx from 'clsx';

export type LoadingVariant = 'spinner' | 'skeleton';

export interface LoadingStateProps {
  variant?: LoadingVariant;
  label?: string;
  className?: string;
  rows?: number;
}

export function LoadingState({
  variant = 'spinner',
  label = '加载中…',
  className,
  rows = 3,
}: LoadingStateProps) {
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
            className="h-4 bg-gray-200 dark:bg-gray-700 rounded animate-pulse"
            style={{ width: `${80 + (i * 5) % 20}%` }}
          />
        ))}
      </div>
    );
  }
  return (
    <div
      role="status"
      aria-live="polite"
      className={clsx('flex items-center gap-2', className)}
    >
      <div
        className="h-5 w-5 border-2 border-t-transparent rounded-full animate-spin border-blue-600"
        aria-hidden
      />
      <span className="text-sm text-gray-600 dark:text-gray-400">{label}</span>
    </div>
  );
}
