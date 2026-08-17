import * as SelectPrimitive from '@radix-ui/react-select';
import clsx from 'clsx';
import { Check, ChevronDown, ChevronUp } from 'lucide-react';
import type { ComponentPropsWithoutRef, ElementRef } from 'react';
import { forwardRef } from 'react';

/**
 * Select component built on Radix UI (U4 from OpenWorker).
 *
 * Accessible select with keyboard navigation, typeahead and proper ARIA
 * combobox/listbox roles — all provided by the Radix primitives.
 * Styled with the semantic color ladder (ink / faint / line).
 *
 * Note: Radix logs a warning unless the trigger is labelled — pair it with a
 * visible `<label htmlFor>` or pass `aria-label` to `SelectTrigger`.
 *
 * @example
 * ```tsx
 * <Select value={model} onValueChange={setModel}>
 *   <SelectTrigger aria-label="Model" className="w-56">
 *     <SelectValue placeholder="Choose a model" />
 *   </SelectTrigger>
 *   <SelectContent>
 *     <SelectGroup>
 *       <SelectLabel>Models</SelectLabel>
 *       <SelectItem value="gpt-4o">GPT-4o</SelectItem>
 *       <SelectItem value="claude">Claude</SelectItem>
 *     </SelectGroup>
 *   </SelectContent>
 * </Select>
 * ```
 */

export const Select = SelectPrimitive.Root;

export const SelectGroup = SelectPrimitive.Group;

export const SelectValue = SelectPrimitive.Value;

export const SelectTrigger = forwardRef<
  ElementRef<typeof SelectPrimitive.Trigger>,
  ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Trigger
    ref={ref}
    className={clsx(
      'flex h-10 w-full items-center justify-between gap-2 rounded-lg border border-line bg-bg px-3 py-2 text-sm text-ink shadow-sm transition-colors',
      'hover:border-line-strong',
      'focus:outline-none focus:ring-2 focus:ring-primary/50',
      'disabled:cursor-not-allowed disabled:opacity-50',
      'data-[placeholder]:text-faint',
      '[&>span]:line-clamp-1',
      className,
    )}
    {...props}
  >
    {children}
    <SelectPrimitive.Icon asChild>
      <ChevronDown aria-hidden className="h-4 w-4 shrink-0 text-faint" />
    </SelectPrimitive.Icon>
  </SelectPrimitive.Trigger>
));
SelectTrigger.displayName = SelectPrimitive.Trigger.displayName;

export const SelectScrollUpButton = forwardRef<
  ElementRef<typeof SelectPrimitive.ScrollUpButton>,
  ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollUpButton>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.ScrollUpButton
    ref={ref}
    className={clsx('flex cursor-default items-center justify-center py-1 text-faint', className)}
    {...props}
  >
    <ChevronUp aria-hidden className="h-4 w-4" />
  </SelectPrimitive.ScrollUpButton>
));
SelectScrollUpButton.displayName = SelectPrimitive.ScrollUpButton.displayName;

export const SelectScrollDownButton = forwardRef<
  ElementRef<typeof SelectPrimitive.ScrollDownButton>,
  ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollDownButton>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.ScrollDownButton
    ref={ref}
    className={clsx('flex cursor-default items-center justify-center py-1 text-faint', className)}
    {...props}
  >
    <ChevronDown aria-hidden className="h-4 w-4" />
  </SelectPrimitive.ScrollDownButton>
));
SelectScrollDownButton.displayName = SelectPrimitive.ScrollDownButton.displayName;

export const SelectContent = forwardRef<
  ElementRef<typeof SelectPrimitive.Content>,
  ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(({ className, children, position = 'popper', ...props }, ref) => (
  <SelectPrimitive.Portal>
    <SelectPrimitive.Content
      ref={ref}
      position={position}
      className={clsx(
        'relative z-50 max-h-96 min-w-[8rem] overflow-hidden rounded-lg border border-line bg-bg shadow-lg',
        'animate-fade-enter',
        className,
      )}
      {...props}
    >
      <SelectScrollUpButton />
      <SelectPrimitive.Viewport
        className={clsx(
          'p-1',
          position === 'popper' &&
            'h-[var(--radix-select-trigger-height)] w-full min-w-[var(--radix-select-content-available-width)]',
        )}
      >
        {children}
      </SelectPrimitive.Viewport>
      <SelectScrollDownButton />
    </SelectPrimitive.Content>
  </SelectPrimitive.Portal>
));
SelectContent.displayName = SelectPrimitive.Content.displayName;

export const SelectLabel = forwardRef<
  ElementRef<typeof SelectPrimitive.Label>,
  ComponentPropsWithoutRef<typeof SelectPrimitive.Label>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Label
    ref={ref}
    className={clsx('py-1.5 pl-8 pr-2 text-xs font-medium text-faint', className)}
    {...props}
  />
));
SelectLabel.displayName = SelectPrimitive.Label.displayName;

export const SelectItem = forwardRef<
  ElementRef<typeof SelectPrimitive.Item>,
  ComponentPropsWithoutRef<typeof SelectPrimitive.Item>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Item
    ref={ref}
    className={clsx(
      'relative flex w-full cursor-default select-none items-center rounded-md py-1.5 pl-8 pr-2 text-sm text-ink outline-none transition-colors',
      'data-[highlighted]:bg-bg-hover',
      'data-[disabled]:pointer-events-none data-[disabled]:opacity-50',
      className,
    )}
    {...props}
  >
    <span className="absolute left-2 flex h-4 w-4 items-center justify-center">
      <SelectPrimitive.ItemIndicator>
        <Check aria-hidden className="h-4 w-4" />
      </SelectPrimitive.ItemIndicator>
    </span>
    <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
  </SelectPrimitive.Item>
));
SelectItem.displayName = SelectPrimitive.Item.displayName;

export const SelectSeparator = forwardRef<
  ElementRef<typeof SelectPrimitive.Separator>,
  ComponentPropsWithoutRef<typeof SelectPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Separator
    ref={ref}
    className={clsx('-mx-1 my-1 h-px bg-line', className)}
    {...props}
  />
));
SelectSeparator.displayName = SelectPrimitive.Separator.displayName;
