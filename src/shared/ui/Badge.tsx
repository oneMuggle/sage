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
