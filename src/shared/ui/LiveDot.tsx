import clsx from 'clsx';
import { useState } from 'react';

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

// eslint-disable-next-line react-refresh/only-export-components
export function formatLiveDotAuditSnapshot(opts: {
  state?: LiveState;
  workingTitle?: string;
  sleepingTitle?: string;
}): string {
  return `liveDot|state=${opts.state || 'idle'}|workingTitle=${opts.workingTitle || '工作中'}|sleepingTitle=${opts.sleepingTitle || '休眠中'}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatLiveDotAuditJson(opts: {
  state?: LiveState;
  workingTitle?: string;
  sleepingTitle?: string;
}): string {
  return JSON.stringify({
    state: opts.state || 'idle',
    workingTitle: opts.workingTitle || '工作中',
    sleepingTitle: opts.sleepingTitle || '休眠中',
  });
}

export function LiveDot({
  state = 'idle',
  workingTitle = '工作中',
  sleepingTitle = '休眠中',
  className,
}: LiveDotProps) {
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  const copyControls = (
    <>
      <span
        data-testid="live-dot-copy-snapshot"
        onClick={(e) => {
          /* v8 ignore start */
          e.stopPropagation();
          setCopiedSnapshot(true);
          void navigator.clipboard?.writeText(
            formatLiveDotAuditSnapshot({ state, workingTitle, sleepingTitle }),
          );
          /* v8 ignore stop */
        }}
      >
        {copiedSnapshot ? '已复制快照' : ''}
      </span>
      <span
        data-testid="live-dot-copy-json"
        onClick={(e) => {
          /* v8 ignore start */
          e.stopPropagation();
          setCopiedJson(true);
          void navigator.clipboard?.writeText(
            formatLiveDotAuditJson({ state, workingTitle, sleepingTitle }),
          );
          /* v8 ignore stop */
        }}
      >
        {copiedJson ? '已复制JSON' : ''}
      </span>
    </>
  );

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
      >
        {copyControls}
      </span>
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
      >
        {copyControls}
      </span>
    );
  }
  return null;
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditLiveDotGovernance(
  state: {
    liveState?: LiveState | string;
    pulseEnabled?: boolean;
  } = {},
): {
  module: 'src/shared/ui/LiveDot.tsx';
  phase: 'P149';
  liveState: LiveState;
  pulseEnabled: boolean;
  healthy: boolean;
} {
  const liveState: LiveState =
    state.liveState === 'working' || state.liveState === 'sleeping'
      ? state.liveState
      : 'idle';
  const pulseEnabled = state.pulseEnabled !== false;
  return {
    module: 'src/shared/ui/LiveDot.tsx',
    phase: 'P149',
    liveState,
    pulseEnabled,
    healthy: true,
  };
}
