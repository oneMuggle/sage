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

// eslint-disable-next-line react-refresh/only-export-components
export function auditProgressGovernance(
  state: {
    value?: number;
  } = {},
): {
  module: 'src/shared/ui/Progress.tsx';
  phase: 'P147';
  clampedValue: number;
  healthy: boolean;
} {
  const raw = typeof state.value === 'number' && Number.isFinite(state.value) ? state.value : 0;
  const clampedValue = Math.min(100, Math.max(0, Math.round(raw)));
  return {
    module: 'src/shared/ui/Progress.tsx',
    phase: 'P147',
    clampedValue,
    healthy: clampedValue >= 0 && clampedValue <= 100,
  };
}
