import clsx from 'clsx';

export interface SkeletonProps {
  className?: string;
  width?: string;
  height?: string;
  circle?: boolean;
}

export function Skeleton({
  className,
  width = '100%',
  height = '1rem',
  circle = false,
}: SkeletonProps) {
  return (
    <div
      role="status"
      aria-busy="true"
      className={clsx(
        'bg-gray-200 dark:bg-gray-700 animate-pulse',
        circle ? 'rounded-full' : 'rounded',
        className,
      )}
      style={{ width, height }}
    />
  );
}
