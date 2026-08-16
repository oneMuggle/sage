import clsx from 'clsx';

/**
 * LiveDot — 活跃度指示原语（U9: Live-Dot vs Attention-Badge 分离）。
 *
 * 语义:表示"正在发生什么"(liveness),而不是"需要你做什么"(attention)。
 * 无数字的小圆点 —— working 时用 accent 色脉冲,sleeping 时用暗色静态点,
 * idle(默认)不渲染。需要"待处理数量"语义时请改用 AttnBadge。
 *
 * 参考: openworker/surfaces/gui/src/components/Sidebar.tsx 的 LiveDot。
 */
export type LiveState = 'working' | 'sleeping' | 'idle';

export interface LiveDotProps {
  /** working=处理中(accent 脉冲点); sleeping=休眠(暗色静态点); idle=不渲染 */
  state?: LiveState;
  /** working 态的 tooltip / 无障碍标签 */
  workingTitle?: string;
  /** sleeping 态的 tooltip / 无障碍标签 */
  sleepingTitle?: string;
  className?: string;
}

export function LiveDot({
  state = 'idle',
  workingTitle = '工作中',
  sleepingTitle = '休眠中',
  className,
}: LiveDotProps) {
  if (state === 'working') {
    return (
      <span
        role="status"
        aria-label={workingTitle}
        title={workingTitle}
        className={clsx(
          'inline-block w-1.5 h-1.5 rounded-full bg-accent animate-pulse flex-shrink-0',
          className,
        )}
      />
    );
  }
  if (state === 'sleeping') {
    return (
      <span
        role="status"
        aria-label={sleepingTitle}
        title={sleepingTitle}
        className={clsx(
          'inline-block w-1.5 h-1.5 rounded-full bg-text-muted opacity-50 flex-shrink-0',
          className,
        )}
      />
    );
  }
  return null;
}
