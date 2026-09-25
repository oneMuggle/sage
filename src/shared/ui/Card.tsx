import clsx from 'clsx';
import type { HTMLAttributes } from 'react';

/**
 * Card 组件 — 对齐 DESIGN.md §7 设计 token 规范
 *
 * 背景：bg-ui-card (--color-card)
 * 边框：border border-ui-border (--color-border)
 * 圆角：rounded-xl (符合 DESIGN.md §6 容器阶梯)
 *
 * 提供最外层 rounded-xl 的标准容器,内部组件按层级递减使用 rounded-lg / rounded-md。
 */
export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
}

export function Card({ className, children, ...props }: CardProps) {
  return (
    <div className={clsx('bg-ui-card border border-ui-border rounded-xl', className)} {...props}>
      {children}
    </div>
  );
}

export interface CardHeaderProps extends HTMLAttributes<HTMLDivElement> {}

export function CardHeader({ className, children, ...props }: CardHeaderProps) {
  return (
    <div className={clsx('px-6 py-4', className)} {...props}>
      {children}
    </div>
  );
}

export interface CardTitleProps extends HTMLAttributes<HTMLHeadingElement> {}

export function CardTitle({ className, children, ...props }: CardTitleProps) {
  return (
    <h3 className={clsx('text-lg font-semibold leading-none tracking-tight', className)} {...props}>
      {children}
    </h3>
  );
}

export interface CardContentProps extends HTMLAttributes<HTMLDivElement> {}

export function CardContent({ className, children, ...props }: CardContentProps) {
  return (
    <div className={clsx('px-6 pb-4', className)} {...props}>
      {children}
    </div>
  );
}
