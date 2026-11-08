import clsx from 'clsx';
import type { ButtonHTMLAttributes } from 'react';

export interface CheckboxProps extends Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  'onChange' | 'type' | 'role' | 'aria-checked'
> {
  checked: boolean;
  onCheckedChange?: (checked: boolean) => void;
}

/** Minimal accessible checkbox primitive (no third-party dependencies). */
export function Checkbox({
  checked,
  onCheckedChange,
  disabled,
  className,
  ...rest
}: CheckboxProps) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onCheckedChange?.(!checked)}
      className={clsx(
        'inline-flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50',
        checked ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-bg',
        disabled && 'cursor-not-allowed opacity-50',
        className,
      )}
      {...rest}
    >
      {checked ? (
        <svg
          aria-hidden
          viewBox="0 0 16 16"
          className="h-3 w-3"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path d="M3 8.5l3 3 7-7" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ) : null}
    </button>
  );
}
