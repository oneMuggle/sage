import { useEffect, useState } from 'react';

/**
 * 共享数字输入 — 允许"先删空再输入"的中间态。
 *
 * 背景：设置页此前每个输入框都在 onChange 里立即 clamp（Math.max(1, …) 或
 * `parseInt(...) || 默认值`），用户按删除键时值立刻弹回 1/默认值，无法清空
 * 后重新输入。本组件把输入值放入本地 draft：
 *
 * - 空字符串 / 非法中间态（"-" / "0."）只更新 draft，不提交；
 * - 合法值立即 clamp 到 [min, max] 并提交（保留既有"改完即保存"体验）；
 * - blur 时若 draft 仍非法，恢复上一次合法值；Enter 提交并失焦，Esc 还原。
 *
 * `integer` 默认 true；小数场景（如重试基础延迟）显式传 false。
 */
export interface NumberFieldProps {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  /** 是否取整，默认 true。 */
  integer?: boolean;
  /**
   * 越界值是否在 onChange 时立即钳制提交。
   * - true（默认）：超上限/下限立即 clamp 并保存（BasicTab 既有语义）；
   * - false：越界只留在 draft，失焦再钳制（编排页防止 0/负数落库）。
   */
  clampOnChange?: boolean;
  testId?: string;
  ariaLabel?: string;
  className?: string;
}

function clamp(value: number, min?: number, max?: number): number {
  let next = value;
  if (min !== undefined) next = Math.max(min, next);
  if (max !== undefined) next = Math.min(max, next);
  return next;
}

export function NumberField({
  value,
  onChange,
  min,
  max,
  step,
  integer = true,
  clampOnChange = true,
  testId,
  ariaLabel,
  className,
}: NumberFieldProps) {
  const [draft, setDraft] = useState(String(value));

  // 外部值变化（其他控件重置默认等）同步到 draft。
  useEffect(() => {
    setDraft(String(value));
  }, [value]);

  const commit = (raw: string): void => {
    if (raw.trim() === '') {
      setDraft(String(value));
      return;
    }
    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) {
      setDraft(String(value));
      return;
    }
    const normalized = clamp(integer ? Math.trunc(parsed) : parsed, min, max);
    setDraft(String(normalized));
    if (normalized !== value) onChange(normalized);
  };

  return (
    <input
      type="number"
      inputMode={integer ? 'numeric' : 'decimal'}
      value={draft}
      min={min}
      max={max}
      step={step}
      data-testid={testId}
      aria-label={ariaLabel}
      className={className}
      onChange={(event) => {
        const raw = event.target.value;
        setDraft(raw);
        if (raw.trim() === '') return;
        const parsed = Number(raw);
        if (!Number.isFinite(parsed)) return;
        // 越界值：clampOnChange=false 时只保留在 draft，不提交 —— 防止
        // 0/负数落库（如 Semaphore(0)）而引发后端挂死；blur 时再钳制。
        const outOfRange =
          (min !== undefined && parsed < min) || (max !== undefined && parsed > max);
        if (outOfRange && !clampOnChange) return;
        const normalized = clamp(integer ? Math.trunc(parsed) : parsed, min, max);
        setDraft(String(normalized));
        if (normalized !== value) onChange(normalized);
      }}
      onBlur={(event) => commit(event.target.value)}
      onKeyDown={(event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          commit(event.currentTarget.value);
          event.currentTarget.blur();
        } else if (event.key === 'Escape') {
          setDraft(String(value));
        }
      }}
    />
  );
}
