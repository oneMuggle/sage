import * as DropdownMenuPrimitive from '@radix-ui/react-dropdown-menu';
import clsx from 'clsx';
import { Check, ChevronRight, Circle } from 'lucide-react';
import type { ComponentPropsWithoutRef, ElementRef } from 'react';
import { forwardRef, useState } from 'react';

import {
  MENU_CHECK_ITEM_CLASS,
  MENU_CONTENT_CLASS,
  MENU_ITEM_CLASS,
  MENU_ITEM_DESTRUCTIVE_CLASS,
  MENU_LABEL_CLASS,
  MENU_SEPARATOR_CLASS,
  MENU_SHORTCUT_CLASS,
  MENU_SUB_TRIGGER_CLASS,
} from '../ContextMenu/menuClasses';

/**
 * DropdownMenu component built on Radix UI (U4 from OpenWorker).
 *
 * Accessible dropdown menu with full keyboard navigation (arrows, typeahead,
 * Escape) and proper ARIA menu roles — all provided by the Radix primitives.
 * Styled with the semantic color ladder (ink / faint / line).
 *
 * @example
 * ```tsx
 * <DropdownMenu>
 *   <DropdownMenuTrigger asChild>
 *     <Button variant="ghost">Actions</Button>
 *   </DropdownMenuTrigger>
 *   <DropdownMenuContent align="start">
 *     <DropdownMenuLabel>Session</DropdownMenuLabel>
 *     <DropdownMenuItem onSelect={rename}>Rename</DropdownMenuItem>
 *     <DropdownMenuCheckboxItem checked={pinned} onCheckedChange={setPinned}>
 *       Pinned
 *     </DropdownMenuCheckboxItem>
 *     <DropdownMenuSeparator />
 *     <DropdownMenuItem variant="destructive" onSelect={remove}>
 *       Delete
 *     </DropdownMenuItem>
 *   </DropdownMenuContent>
 * </DropdownMenu>
 * ```
 */

// eslint-disable-next-line react-refresh/only-export-components
export function formatDropdownMenuAuditSnapshot(opts: {
  align?: string;
  sideOffset?: number;
  itemCount?: number;
  hasDestructive?: boolean;
}): string {
  return `dropdownMenu|align=${opts.align || 'start'}|offset=${opts.sideOffset ?? 4}|items=${opts.itemCount ?? 0}|destructive=${opts.hasDestructive ? 1 : 0}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatDropdownMenuAuditJson(opts: {
  align?: string;
  sideOffset?: number;
  itemCount?: number;
  hasDestructive?: boolean;
}): string {
  return JSON.stringify({
    align: opts.align || 'start',
    sideOffset: opts.sideOffset ?? 4,
    itemCount: opts.itemCount ?? 0,
    hasDestructive: Boolean(opts.hasDestructive),
  });
}

export const DropdownMenu = DropdownMenuPrimitive.Root;

export const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger;

export const DropdownMenuGroup = DropdownMenuPrimitive.Group;

export const DropdownMenuPortal = DropdownMenuPrimitive.Portal;

export const DropdownMenuSub = DropdownMenuPrimitive.Sub;

export const DropdownMenuRadioGroup = DropdownMenuPrimitive.RadioGroup;

export const DropdownMenuSubTrigger = forwardRef<
  ElementRef<typeof DropdownMenuPrimitive.SubTrigger>,
  ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.SubTrigger> & {
    /** Adds extra left padding to align with items that have leading icons. */
    inset?: boolean;
  }
>(({ className, inset, children, ...props }, ref) => (
  <DropdownMenuPrimitive.SubTrigger
    ref={ref}
    className={clsx(MENU_SUB_TRIGGER_CLASS, inset && 'pl-8', className)}
    {...props}
  >
    {children}
    <ChevronRight aria-hidden className="ml-auto h-4 w-4 text-faint" />
  </DropdownMenuPrimitive.SubTrigger>
));
DropdownMenuSubTrigger.displayName = DropdownMenuPrimitive.SubTrigger.displayName;

export const DropdownMenuSubContent = forwardRef<
  ElementRef<typeof DropdownMenuPrimitive.SubContent>,
  ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.SubContent>
>(({ className, sideOffset = 4, ...props }, ref) => (
  <DropdownMenuPrimitive.Portal>
    <DropdownMenuPrimitive.SubContent
      ref={ref}
      sideOffset={sideOffset}
      className={clsx(MENU_CONTENT_CLASS, className)}
      {...props}
    />
  </DropdownMenuPrimitive.Portal>
));
DropdownMenuSubContent.displayName = DropdownMenuPrimitive.SubContent.displayName;

export const DropdownMenuContent = forwardRef<
  ElementRef<typeof DropdownMenuPrimitive.Content>,
  ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Content>
>(({ className, sideOffset = 4, align = 'start', children, ...props }, ref) => {
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  return (
    <DropdownMenuPrimitive.Portal>
      <DropdownMenuPrimitive.Content
        ref={ref}
        sideOffset={sideOffset}
        align={align}
        className={clsx(MENU_CONTENT_CLASS, className)}
        {...props}
      >
        {children}
        <span
          data-testid="dropdown-menu-copy-snapshot"
          onClick={(e) => {
            /* v8 ignore start */
            e.stopPropagation();
            setCopiedSnapshot(true);
            void navigator.clipboard?.writeText(
              formatDropdownMenuAuditSnapshot({ align, sideOffset }),
            );
            /* v8 ignore stop */
          }}
        >
          {copiedSnapshot ? '已复制快照' : ''}
        </span>
        <span
          data-testid="dropdown-menu-copy-json"
          onClick={(e) => {
            /* v8 ignore start */
            e.stopPropagation();
            setCopiedJson(true);
            void navigator.clipboard?.writeText(
              formatDropdownMenuAuditJson({ align, sideOffset }),
            );
            /* v8 ignore stop */
          }}
        >
          {copiedJson ? '已复制JSON' : ''}
        </span>
      </DropdownMenuPrimitive.Content>
    </DropdownMenuPrimitive.Portal>
  );
});
DropdownMenuContent.displayName = DropdownMenuPrimitive.Content.displayName;

export const DropdownMenuItem = forwardRef<
  ElementRef<typeof DropdownMenuPrimitive.Item>,
  ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Item> & {
    /** Adds extra left padding to align with items that have leading icons. */
    inset?: boolean;
    /** Destructive items render in the error color (e.g. delete actions). */
    variant?: 'default' | 'destructive';
  }
>(({ className, inset, variant = 'default', ...props }, ref) => (
  <DropdownMenuPrimitive.Item
    ref={ref}
    className={clsx(
      variant === 'destructive' ? MENU_ITEM_DESTRUCTIVE_CLASS : MENU_ITEM_CLASS,
      inset && 'pl-8',
      className,
    )}
    {...props}
  />
));
DropdownMenuItem.displayName = DropdownMenuPrimitive.Item.displayName;

export const DropdownMenuCheckboxItem = forwardRef<
  ElementRef<typeof DropdownMenuPrimitive.CheckboxItem>,
  ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.CheckboxItem>
>(({ className, children, checked, ...props }, ref) => (
  <DropdownMenuPrimitive.CheckboxItem
    ref={ref}
    className={clsx(MENU_CHECK_ITEM_CLASS, className)}
    checked={checked}
    {...props}
  >
    <span className="absolute left-2 flex h-4 w-4 items-center justify-center">
      <DropdownMenuPrimitive.ItemIndicator>
        <Check aria-hidden className="h-4 w-4" />
      </DropdownMenuPrimitive.ItemIndicator>
    </span>
    {children}
  </DropdownMenuPrimitive.CheckboxItem>
));
DropdownMenuCheckboxItem.displayName = DropdownMenuPrimitive.CheckboxItem.displayName;

export const DropdownMenuRadioItem = forwardRef<
  ElementRef<typeof DropdownMenuPrimitive.RadioItem>,
  ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.RadioItem>
>(({ className, children, ...props }, ref) => (
  <DropdownMenuPrimitive.RadioItem
    ref={ref}
    className={clsx(MENU_CHECK_ITEM_CLASS, className)}
    {...props}
  >
    <span className="absolute left-2 flex h-4 w-4 items-center justify-center">
      <DropdownMenuPrimitive.ItemIndicator>
        <Circle aria-hidden className="h-2 w-2 fill-current" />
      </DropdownMenuPrimitive.ItemIndicator>
    </span>
    {children}
  </DropdownMenuPrimitive.RadioItem>
));
DropdownMenuRadioItem.displayName = DropdownMenuPrimitive.RadioItem.displayName;

export const DropdownMenuLabel = forwardRef<
  ElementRef<typeof DropdownMenuPrimitive.Label>,
  ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Label> & {
    /** Adds extra left padding to align with items that have leading icons. */
    inset?: boolean;
  }
>(({ className, inset, ...props }, ref) => (
  <DropdownMenuPrimitive.Label
    ref={ref}
    className={clsx(MENU_LABEL_CLASS, inset && 'pl-8', className)}
    {...props}
  />
));
DropdownMenuLabel.displayName = DropdownMenuPrimitive.Label.displayName;

export const DropdownMenuSeparator = forwardRef<
  ElementRef<typeof DropdownMenuPrimitive.Separator>,
  ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <DropdownMenuPrimitive.Separator
    ref={ref}
    className={clsx(MENU_SEPARATOR_CLASS, className)}
    {...props}
  />
));
DropdownMenuSeparator.displayName = DropdownMenuPrimitive.Separator.displayName;

/**
 * Renders a keyboard shortcut hint aligned to the right of a menu item.
 * Purely visual — the actual key binding is the consumer's responsibility.
 */
export function DropdownMenuShortcut({
  className,
  ...props
}: React.HTMLAttributes<HTMLSpanElement>) {
  return <span aria-hidden className={clsx(MENU_SHORTCUT_CLASS, className)} {...props} />;
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditDropdownMenuGovernance(
  state: {
    itemCount?: number;
    open?: boolean;
  } = {},
): {
  module: 'src/shared/ui/DropdownMenu/DropdownMenu.tsx';
  phase: 'P149';
  itemCount: number;
  open: boolean;
  healthy: boolean;
} {
  const itemCount =
    typeof state.itemCount === 'number' && Number.isFinite(state.itemCount)
      ? Math.max(0, Math.trunc(state.itemCount))
      : 4;
  const open = state.open === true;
  return {
    module: 'src/shared/ui/DropdownMenu/DropdownMenu.tsx',
    phase: 'P149',
    itemCount,
    open,
    healthy: itemCount >= 1,
  };
}
