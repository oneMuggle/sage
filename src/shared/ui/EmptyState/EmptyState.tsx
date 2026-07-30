import type { ComponentType, ReactNode } from 'react';

export interface EmptyStateProps {
  /** Icon component to display above title */
  icon?: ComponentType<{ className?: string }>;
  /** Main heading text */
  title: string;
  /** Optional description text below title */
  description?: string;
  /** Optional action button/link */
  action?: ReactNode;
  /** Additional CSS classes */
  className?: string;
}

/**
 * Generic empty state placeholder (U16 from OpenWorker).
 *
 * Used across the app for consistent empty state presentation.
 * Replaces ad-hoc empty state implementations in various features.
 *
 * @example
 * ```tsx
 * <EmptyState
 *   icon={MessageCircleIcon}
 *   title="还没有消息"
 *   description="开始一段新对话吧"
 *   action={<Button onClick={...}>新建对话</Button>}
 * />
 * ```
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={`flex flex-col items-center justify-center py-12 text-center ${className ?? ''}`}
    >
      {Icon && <Icon className="h-12 w-12 text-faint mb-4" />}
      <h3 className="text-ink text-lg font-medium">{title}</h3>
      {description && <p className="text-muted mt-1">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
