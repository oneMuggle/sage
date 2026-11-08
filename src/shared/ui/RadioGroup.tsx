import clsx from 'clsx';
import { createContext, useContext, type ReactNode } from 'react';

interface RadioGroupContextValue {
  value: string;
  onValueChange?: (value: string) => void;
}

const RadioGroupContext = createContext<RadioGroupContextValue | null>(null);

export interface RadioGroupProps {
  value: string;
  onValueChange?: (value: string) => void;
  children: ReactNode;
  className?: string;
  'data-testid'?: string;
}

/** Minimal accessible radio group primitive (no third-party dependencies). */
export function RadioGroup({ value, onValueChange, children, className, ...rest }: RadioGroupProps) {
  return (
    <RadioGroupContext.Provider value={{ value, onValueChange }}>
      <div role="radiogroup" className={clsx('space-y-1', className)} {...rest}>
        {children}
      </div>
    </RadioGroupContext.Provider>
  );
}

export interface RadioGroupItemProps {
  value: string;
  disabled?: boolean;
  className?: string;
  'data-testid'?: string;
  'aria-label'?: string;
}

export function RadioGroupItem({ value, disabled, className, ...rest }: RadioGroupItemProps) {
  const context = useContext(RadioGroupContext);
  const checked = context?.value === value;
  return (
    <button
      type="button"
      role="radio"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => context?.onValueChange?.(value)}
      className={clsx(
        'mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50',
        checked ? 'border-primary' : 'border-border',
        disabled && 'cursor-not-allowed opacity-50',
        className,
      )}
      {...rest}
    >
      {checked ? <span className="h-2 w-2 rounded-full bg-primary" /> : null}
    </button>
  );
}
