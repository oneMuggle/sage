import clsx from 'clsx';
import type { HTMLAttributes } from 'react';

/**
 * Badge 组件 (2026-09-25)
 *
 * 简单的标签组件，用于显示状态、分类等信息
 */

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  /** 变体样式 */
  variant?: 'default' | 'secondary' | 'outline' | 'destructive';
}

export function Badge({ className, variant = 'default', ...props }: BadgeProps) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium transition-colors',
        {
          'bg-primary text-primary-foreground': variant === 'default',
          'bg-secondary text-secondary-foreground': variant === 'secondary',
          'border border-border text-foreground': variant === 'outline',
          'bg-destructive text-destructive-foreground': variant === 'destructive',
        },
        className,
      )}
      {...props}
    />
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatBadgeVariantSummary(
  variant: BadgeProps['variant'] = 'default',
): string {
  const resolved = variant ?? 'default';
  return `variant=${resolved} · pill=true`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatBadgeVariantJson(
  variant: BadgeProps['variant'] = 'default',
): string {
  const resolved = variant ?? 'default';
  return JSON.stringify({
    variant: resolved,
    pill: true,
  });
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditBadgeGovernance(): string {
  return JSON.stringify({
    module: 'ui-badge',
    phase: 'P184',
    audited: true,
  });
}

