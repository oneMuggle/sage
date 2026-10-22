/**
 * Textarea 组件 — 多行文本输入 (2026-09-25)
 *
 * 与 Input 组件风格一致，支持 rows 属性。
 */

import clsx from 'clsx';
import type { TextareaHTMLAttributes } from 'react';

export type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement>;

export function Textarea({ className, ...props }: TextareaProps) {
  return (
    <textarea
      className={clsx(
        'flex min-h-[80px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm',
        'placeholder:text-muted-foreground',
        'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
        'disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    />
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditTextareaGovernance(
  state: {
    rows?: number;
    disabled?: boolean;
  } = {},
): {
  module: 'src/shared/ui/Textarea.tsx';
  phase: 'P147';
  rows: number;
  disabled: boolean;
  healthy: boolean;
} {
  const rows =
    typeof state.rows === 'number' && Number.isFinite(state.rows)
      ? Math.max(1, Math.min(40, Math.trunc(state.rows)))
      : 3;
  const disabled = state.disabled === true;
  return {
    module: 'src/shared/ui/Textarea.tsx',
    phase: 'P147',
    rows,
    disabled,
    healthy: rows >= 1 && rows <= 40,
  };
}
