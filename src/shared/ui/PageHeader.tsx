// src/shared/ui/PageHeader.tsx
import type { ReactNode } from 'react';

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  testId?: string;
}

/**
 * UI-R2-P2-2: 二级页面统一 48px (h-12) 顶栏外壳。
 * 与 ChatHeaderBar / Settings / PanelShell 保持同一套 48px 水平基线与语义字号。
 */
export function PageHeader({
  title,
  subtitle,
  actions,
  testId = 'page-header',
}: PageHeaderProps) {
  return (
    <header
      data-testid={testId}
      className="h-12 flex items-center justify-between px-5 border-b border-border bg-surface flex-shrink-0 gap-3"
    >
      <div className="flex items-baseline gap-2.5 min-w-0">
        <h1 className="text-ui-lg font-semibold text-text truncate">{title}</h1>
        {subtitle && (
          <p className="text-ui-xs text-text-secondary truncate hidden sm:block">{subtitle}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </header>
  );
}
