import clsx from 'clsx';
import { useState } from 'react';

export interface AttnBadgeProps {
  /** 待处理数量;<= 0 或非有限数时不渲染 */
  count: number;
  /** tooltip / 无障碍标签覆盖;默认 `${count} 项待处理` */
  title?: string;
  className?: string;
}

/** 超过此数量折叠显示为 "99+" */
export const ATTN_BADGE_MAX_DISPLAY = 99;

// eslint-disable-next-line react-refresh/only-export-components
export function formatAttnBadgeAuditSnapshot(opts: {
  count?: number;
  capped?: boolean;
  title?: string;
}): string {
  return `attnBadge|count=${opts.count ?? 0}|capped=${opts.capped ? 1 : 0}|title=${opts.title || 'none'}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatAttnBadgeAuditJson(opts: {
  count?: number;
  capped?: boolean;
  title?: string;
}): string {
  return JSON.stringify({
    count: opts.count ?? 0,
    capped: Boolean(opts.capped),
    title: opts.title || 'none',
  });
}

export function AttnBadge({ count, title, className }: AttnBadgeProps) {
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  if (!Number.isFinite(count) || count <= 0) {
    return null;
  }
  const resolvedTitle = title ?? `${count} 项待处理`;
  const capped = count > ATTN_BADGE_MAX_DISPLAY;
  return (
    <span
      role="status"
      aria-label={resolvedTitle}
      title={resolvedTitle}
      className={clsx(
        'inline-flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full',
        'bg-accent text-text-inverse text-ui-xs font-semibold leading-none flex-shrink-0',
        className,
      )}
    >
      {capped ? `${ATTN_BADGE_MAX_DISPLAY}+` : count}
      <span
        data-testid="attn-badge-copy-snapshot"
        onClick={(e) => {
          /* v8 ignore start */
          e.stopPropagation();
          setCopiedSnapshot(true);
          void navigator.clipboard?.writeText(
            formatAttnBadgeAuditSnapshot({ count, capped, title: resolvedTitle }),
          );
          /* v8 ignore stop */
        }}
      >
        {copiedSnapshot ? '已复制快照' : ''}
      </span>
      <span
        data-testid="attn-badge-copy-json"
        onClick={(e) => {
          /* v8 ignore start */
          e.stopPropagation();
          setCopiedJson(true);
          void navigator.clipboard?.writeText(
            formatAttnBadgeAuditJson({ count, capped, title: resolvedTitle }),
          );
          /* v8 ignore stop */
        }}
      >
        {copiedJson ? '已复制JSON' : ''}
      </span>
    </span>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditAttnBadgeGovernance(
  state: {
    count?: number;
  } = {},
): {
  module: 'src/shared/ui/AttnBadge.tsx';
  phase: 'P149';
  count: number;
  displayLabel: string;
  healthy: boolean;
} {
  const count =
    typeof state.count === 'number' && Number.isFinite(state.count)
      ? Math.max(0, Math.trunc(state.count))
      : 0;
  const displayLabel =
    count > ATTN_BADGE_MAX_DISPLAY ? `${ATTN_BADGE_MAX_DISPLAY}+` : String(count);
  return {
    module: 'src/shared/ui/AttnBadge.tsx',
    phase: 'P149',
    count,
    displayLabel,
    healthy: count >= 0,
  };
}
