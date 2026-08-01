/**
 * TwoStepDelete — U12: 两步式删除确认按钮（无 modal）
 *
 * 借鉴 OpenWorker Sidebar 的 rowActions 模式：第一次点击进入 armed 状态
 * （显示 armedLabel 文案），第二次点击才真正触发 onConfirm；armed 状态在
 * disarmTimeoutMs 后自动解除，按 Esc 可提前解除。
 *
 * 适用于行/卡片内联的 destructive action（会话删除、技能卸载、记忆删除等）——
 * 比 modal 确认轻量，但同样能防误操作。
 */
import { Trash2 } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';

const DEFAULT_DISARM_TIMEOUT_MS = 3000;

const BASE_CLASS =
  'inline-flex items-center gap-1 rounded transition-colors disabled:cursor-not-allowed disabled:opacity-50';
const IDLE_CLASS = 'text-muted hover:bg-error/10 hover:text-error';
const ARMED_CLASS = 'bg-error font-medium text-text-inverse';

export interface TwoStepDeleteProps {
  /** 真正执行删除的回调 — 仅在 armed 状态下的第二次点击触发 */
  onConfirm: () => void;
  disabled?: boolean;
  /** idle 状态的 title / aria-label（默认 "删除"） */
  label?: string;
  /** armed 状态展示的文案，同时作为 title / aria-label（默认 "确认删除?"） */
  armedLabel?: string;
  /** armed 后自动解除的毫秒数（默认 3000） */
  disarmTimeoutMs?: number;
  /** 自定义图标；默认 Trash2 */
  icon?: ReactNode;
  className?: string;
  'data-testid'?: string;
}

export function TwoStepDelete({
  onConfirm,
  disabled = false,
  label = '删除',
  armedLabel = '确认删除?',
  disarmTimeoutMs = DEFAULT_DISARM_TIMEOUT_MS,
  icon,
  className,
  'data-testid': dataTestId,
}: TwoStepDeleteProps) {
  const [armed, setArmed] = useState(false);
  const disarmTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  // 卸载时清理定时器，避免对已卸载组件 setState
  useEffect(() => clearTimer, []);

  const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    // 行/卡片级按钮：不得触发外层容器的 onSelect
    e.stopPropagation();
    if (disabled) return;
    if (armed) {
      disarm();
      onConfirm();
    } else {
      setArmed(true);
      disarmTimer.current = setTimeout(disarm, disarmTimeoutMs);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === 'Escape' && armed) {
      e.stopPropagation();
      disarm();
    }
  };

  return (
    <button
      type="button"
      data-testid={dataTestId}
      data-state={armed ? 'armed' : 'idle'}
      aria-label={armed ? armedLabel : label}
      title={armed ? armedLabel : label}
      disabled={disabled}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      className={`${BASE_CLASS} ${armed ? ARMED_CLASS : IDLE_CLASS}${className ? ` ${className}` : ''}`}
    >
      {icon ?? <Trash2 className="h-4 w-4" />}
      {armed && <span className="whitespace-nowrap text-xs">{armedLabel}</span>}
    </button>
  );
}
