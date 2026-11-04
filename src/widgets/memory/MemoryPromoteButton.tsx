/**
 * MemoryPromoteButton — M3-Task 7: 把一条私有记忆提升为共享层。
 *
 * 两步确认（与项目内 destructive action 的既有惯例一致）：第一次点击进入
 * armed 状态并显示确认文案，第二次点击才真正调用 ``onPromote``；armed
 * 状态在 ``disarmTimeoutMs`` 后自动解除，按 Esc 可提前解除。
 *
 * 语义提示（不可逆）：提升后该记忆对**所有**专家可见，且归属从"某专家
 * 私有"变为"共享层"（后端写审计行留痕）。
 */
import { Share2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

const DEFAULT_DISARM_TIMEOUT_MS = 3000;

export interface MemoryPromoteButtonProps {
  /** 待提升的记忆 ID —— 回调按 ID 传回，调用方据此定位行。 */
  memoryId: string;
  /** 真正执行提升的回调。 */
  onPromote: (memoryId: string) => void | Promise<void>;
  disabled?: boolean;
  /** idle 文案（默认「提升为共享」）。 */
  label?: string;
  /** armed 文案（默认「确认公开?」）。 */
  armedLabel?: string;
  /** armed 后自动解除的毫秒数（默认 3000）。 */
  disarmTimeoutMs?: number;
  className?: string;
  'data-testid'?: string;
}

export function MemoryPromoteButton({
  memoryId,
  onPromote,
  disabled = false,
  label = '提升为共享',
  armedLabel = '确认公开?',
  disarmTimeoutMs = DEFAULT_DISARM_TIMEOUT_MS,
  className,
  'data-testid': dataTestId,
}: MemoryPromoteButtonProps) {
  const [armed, setArmed] = useState(false);
  const [pending, setPending] = useState(false);
  const disarmTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const clearTimer = () => {
    if (disarmTimer.current !== null) {
      clearTimeout(disarmTimer.current);
      disarmTimer.current = null;
    }
  };

  const disarm = () => {
    clearTimer();
    setArmed(false);
  };

  // 卸载时清理定时器，并阻止迟到的 Promise 回调再 setState
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (disarmTimer.current !== null) {
        clearTimeout(disarmTimer.current);
        disarmTimer.current = null;
      }
    };
  }, []);

  const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    // 行/卡片级按钮：不得触发外层容器的 onSelect
    e.stopPropagation();
    if (disabled || pending) return;
    if (armed) {
      disarm();
      setPending(true);
      void Promise.resolve(onPromote(memoryId)).finally(() => {
        if (mountedRef.current) {
          setPending(false);
        }
      });
      return;
    }
    setArmed(true);
    disarmTimer.current = setTimeout(disarm, disarmTimeoutMs);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === 'Escape' && armed) {
      e.stopPropagation();
      disarm();
    }
  };

  const testId = dataTestId ?? `memory-promote-${memoryId}`;

  return (
    <button
      type="button"
      data-testid={testId}
      data-state={armed ? 'armed' : 'idle'}
      aria-label={armed ? armedLabel : label}
      title={armed ? armedLabel : `${label}（提升后所有专家可见）`}
      disabled={disabled || pending}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      className={
        'inline-flex items-center gap-1 px-2 py-0.5 border rounded text-ui-2xs transition-colors ' +
        'disabled:opacity-50 ' +
        (armed
          ? 'border-primary bg-primary/10 text-primary'
          : 'border-border text-muted hover:text-primary hover:border-primary') +
        (className ? ` ${className}` : '')
      }
    >
      <Share2 className="h-3 w-3" />
      {armed ? (
        <span className="whitespace-nowrap">{pending ? '公开中…' : armedLabel}</span>
      ) : (
        label
      )}
    </button>
  );
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditMemoryPromoteButtonGovernance(): string {
  return JSON.stringify({
    module: 'memory-promote-button',
    phase: 'M3-Task7',
    audited: true,
  });
}
