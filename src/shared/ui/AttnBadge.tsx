import clsx from 'clsx';

/**
 * AttnBadge — 待处理数量徽标原语（U9: Live-Dot vs Attention-Badge 分离）。
 *
 * 语义:表示"需要你做什么"(attention),而不是"正在发生什么"(liveness)。
 * 带数字的 accent 气泡 —— count <= 0 时不渲染(安静),超过上限显示 "99+"。
 * 需要"活动状态"语义时请改用 LiveDot。
 *
 * 参考: openworker/surfaces/gui/src/components/Sidebar.tsx 的 AttnBadge
 * (OpenWorker 刻意用中性色; Sage 按 U9 计划使用 accent 色强调待办)。
 */
export interface AttnBadgeProps {
  /** 待处理数量;<= 0 或非有限数时不渲染 */
  count: number;
  /** tooltip / 无障碍标签覆盖;默认 `${count} 项待处理` */
  title?: string;
  className?: string;
}

/** 超过此数量折叠显示为 "99+" */
export const ATTN_BADGE_MAX_DISPLAY = 99;

export function AttnBadge({ count, title, className }: AttnBadgeProps) {
  if (!Number.isFinite(count) || count <= 0) {
    return null;
  }
  const resolvedTitle = title ?? `${count} 项待处理`;
  return (
    <span
      role="status"
      aria-label={resolvedTitle}
      title={resolvedTitle}
      className={clsx(
        'inline-flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full',
        'bg-accent text-text-inverse text-[10px] font-semibold leading-none flex-shrink-0',
        className,
      )}
    >
      {count > ATTN_BADGE_MAX_DISPLAY ? `${ATTN_BADGE_MAX_DISPLAY}+` : count}
    </span>
  );
}
