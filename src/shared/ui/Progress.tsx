import clsx from 'clsx';

/**
 * Progress 组件 (2026-09-25)
 *
 * 简单的进度条组件，用于显示百分比进度
 */

export interface ProgressProps {
  /** 进度值 0-100 */
  value: number;
  /** 自定义 className */
  className?: string;
}

export function Progress({ value, className }: ProgressProps) {
  // 限制值在 0-100 范围内
  const clampedValue = Math.max(0, Math.min(100, value));

  return (
    <div
      className={clsx('relative h-2 w-full overflow-hidden rounded-full bg-secondary', className)}
    >
      <div
        className="h-full bg-primary transition-all duration-300 ease-in-out"
        style={{ width: `${clampedValue}%` }}
      />
    </div>
  );
}
