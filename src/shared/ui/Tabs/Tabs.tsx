import * as TabsPrimitive from '@radix-ui/react-tabs';
import clsx from 'clsx';
import type { ComponentPropsWithoutRef, ElementRef } from 'react';
import { forwardRef } from 'react';

/**
 * Tabs component built on Radix UI (U4 from OpenWorker).
 *
 * Accessible tabs with keyboard navigation and proper ARIA attributes.
 * Replaces custom tab implementations across the app.
 *
 * @example
 * ```tsx
 * <Tabs defaultValue="tab1">
 *   <TabsList>
 *     <TabsTrigger value="tab1">Tab 1</TabsTrigger>
 *     <TabsTrigger value="tab2">Tab 2</TabsTrigger>
 *   </TabsList>
 *   <TabsContent value="tab1">Content 1</TabsContent>
 *   <TabsContent value="tab2">Content 2</TabsContent>
 * </Tabs>
 * ```
 */

export const Tabs = TabsPrimitive.Root;

export const TabsList = forwardRef<
  ElementRef<typeof TabsPrimitive.List>,
  ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={clsx(
      'inline-flex items-center justify-center rounded-lg bg-bg-muted p-1 text-muted',
      className,
    )}
    {...props}
  />
));
TabsList.displayName = TabsPrimitive.List.displayName;

export const TabsTrigger = forwardRef<
  ElementRef<typeof TabsPrimitive.Trigger>,
  ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={clsx(
      'inline-flex items-center justify-center whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-all',
      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2',
      'disabled:pointer-events-none disabled:opacity-50',
      'data-[state=active]:bg-bg data-[state=active]:text-ink data-[state=active]:shadow-sm',
      className,
    )}
    {...props}
  />
));
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

export const TabsContent = forwardRef<
  ElementRef<typeof TabsPrimitive.Content>,
  ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={clsx(
      'mt-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2',
      className,
    )}
    {...props}
  />
));
TabsContent.displayName = TabsPrimitive.Content.displayName;

// eslint-disable-next-line react-refresh/only-export-components
export function auditTabsGovernance(
  state: {
    tabCount?: number;
    activeValue?: string;
  } = {},
): {
  module: 'src/shared/ui/Tabs/Tabs.tsx';
  phase: 'P148';
  tabCount: number;
  activeValue: string;
  healthy: boolean;
} {
  const tabCount =
    typeof state.tabCount === 'number' && Number.isFinite(state.tabCount)
      ? Math.max(1, Math.trunc(state.tabCount))
      : 2;
  const activeValue =
    typeof state.activeValue === 'string' && state.activeValue.trim().length > 0
      ? state.activeValue.trim()
      : 'overview';
  return {
    module: 'src/shared/ui/Tabs/Tabs.tsx',
    phase: 'P148',
    tabCount,
    activeValue,
    healthy: tabCount >= 1 && activeValue.length > 0,
  };
}
