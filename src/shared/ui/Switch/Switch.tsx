import * as SwitchPrimitive from '@radix-ui/react-switch';
import clsx from 'clsx';
import type { ComponentPropsWithoutRef, ElementRef } from 'react';
import { forwardRef } from 'react';

/**
 * Switch component built on Radix UI (U4 from OpenWorker).
 *
 * Accessible toggle switch: Radix renders `role="switch"` with
 * `aria-checked` and supports keyboard toggling (Space/Enter) out of the box.
 * Styled with the semantic color ladder (primary / line-strong).
 *
 * The thumb is rendered automatically; pass children only to fully replace it.
 * Pair with a visible `<label htmlFor>` or pass `aria-label` for accessibility.
 *
 * @example
 * ```tsx
 * <label htmlFor="auto-refresh" className="flex items-center gap-2 text-sm text-ink">
 *   <Switch id="auto-refresh" checked={enabled} onCheckedChange={setEnabled} />
 *   Auto refresh
 * </label>
 * ```
 */

export const SwitchThumb = forwardRef<
  ElementRef<typeof SwitchPrimitive.Thumb>,
  ComponentPropsWithoutRef<typeof SwitchPrimitive.Thumb>
>(({ className, ...props }, ref) => (
  <SwitchPrimitive.Thumb
    ref={ref}
    className={clsx(
      'pointer-events-none block h-5 w-5 rounded-full bg-white shadow-md transition-transform',
      'data-[state=checked]:translate-x-5 data-[state=unchecked]:translate-x-0',
      className,
    )}
    {...props}
  />
));
SwitchThumb.displayName = SwitchPrimitive.Thumb.displayName;

export const Switch = forwardRef<
  ElementRef<typeof SwitchPrimitive.Root>,
  ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>
>(({ className, children, ...props }, ref) => (
  <SwitchPrimitive.Root
    ref={ref}
    className={clsx(
      'inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors',
      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-2 focus-visible:ring-offset-bg',
      'disabled:cursor-not-allowed disabled:opacity-50',
      'data-[state=checked]:bg-primary data-[state=unchecked]:bg-line-strong',
      className,
    )}
    {...props}
  >
    {children ?? <SwitchThumb />}
  </SwitchPrimitive.Root>
));
Switch.displayName = SwitchPrimitive.Root.displayName;
