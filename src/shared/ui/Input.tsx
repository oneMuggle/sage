import { clsx } from 'clsx';
import { InputHTMLAttributes, forwardRef } from 'react';

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  error?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, error, ...props }, ref) => {
    return (
      <input
        className={clsx(
          'w-full rounded-lg border px-3 py-2 text-sm',
          'bg-bg-subtle',
          'border-border',
          'focus:outline-none focus:ring-2 focus:ring-primary/50',
          'disabled:opacity-50 disabled:cursor-not-allowed',
          'placeholder:text-muted',
          error && 'border-error focus:ring-error/50',
          className,
        )}
        ref={ref}
        {...props}
      />
    );
  },
);

Input.displayName = 'Input';

// eslint-disable-next-line react-refresh/only-export-components
export function formatInputFieldSummary(error = false, disabled = false): string {
  return `error=${Boolean(error)} · disabled=${Boolean(disabled)}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatInputFieldJson(error = false, disabled = false): string {
  return JSON.stringify({
    error: Boolean(error),
    disabled: Boolean(disabled),
  });
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditInputGovernance(): string {
  return JSON.stringify({
    module: 'ui-input',
    phase: 'P184',
    audited: true,
  });
}

