import * as DialogPrimitive from '@radix-ui/react-dialog';
import clsx from 'clsx';
import { X } from 'lucide-react';
import type { ComponentPropsWithoutRef, ElementRef, HTMLAttributes } from 'react';
import { forwardRef } from 'react';

/**
 * Dialog component built on Radix UI (U4 from OpenWorker).
 *
 * Accessible modal dialog: Radix provides `role="dialog"`,
 * `aria-modal="true"`, focus trapping and Escape-to-close out of the box.
 * Pair every dialog with `DialogTitle` (and ideally `DialogDescription`)
 * so screen readers can announce it — Radix warns otherwise.
 * Styled with the semantic color ladder (ink / faint / line / overlay).
 *
 * @example
 * ```tsx
 * <Dialog>
 *   <DialogTrigger asChild>
 *     <Button variant="secondary">Export</Button>
 *   </DialogTrigger>
 *   <DialogContent>
 *     <DialogHeader>
 *       <DialogTitle>Export session</DialogTitle>
 *       <DialogDescription>Choose a format for the exported file.</DialogDescription>
 *     </DialogHeader>
 *     <DialogFooter>
 *       <DialogClose asChild>
 *         <Button variant="ghost">Cancel</Button>
 *       </DialogClose>
 *       <Button onClick={doExport}>Export</Button>
 *     </DialogFooter>
 *   </DialogContent>
 * </Dialog>
 * ```
 */

export const Dialog = DialogPrimitive.Root;

export const DialogTrigger = DialogPrimitive.Trigger;

export const DialogPortal = DialogPrimitive.Portal;

export const DialogClose = DialogPrimitive.Close;

export const DialogOverlay = forwardRef<
  ElementRef<typeof DialogPrimitive.Overlay>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={clsx('fixed inset-0 z-50 bg-overlay animate-fade-enter', className)}
    {...props}
  />
));
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName;

export const DialogContent = forwardRef<
  ElementRef<typeof DialogPrimitive.Content>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
    /** Set to false for confirm-style dialogs that require an explicit choice. */
    showCloseButton?: boolean;
  }
>(({ className, children, showCloseButton = true, ...props }, ref) => (
  <DialogPortal>
    <DialogOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={clsx(
        'fixed left-1/2 top-1/2 z-50 grid w-full max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4',
        'rounded-xl border border-line bg-bg p-6 shadow-xl',
        'focus:outline-none',
        'animate-fade-enter',
        className,
      )}
      {...props}
    >
      {children}
      {showCloseButton && (
        <DialogPrimitive.Close
          aria-label="Close"
          className={clsx(
            'absolute right-4 top-4 rounded-md p-1 text-faint transition-colors',
            'hover:bg-bg-hover hover:text-ink',
            'focus:outline-none focus:ring-2 focus:ring-primary/50',
            'disabled:pointer-events-none',
          )}
        >
          <X aria-hidden className="h-4 w-4" />
        </DialogPrimitive.Close>
      )}
    </DialogPrimitive.Content>
  </DialogPortal>
));
DialogContent.displayName = DialogPrimitive.Content.displayName;

export function DialogHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={clsx('flex flex-col gap-1.5', className)} {...props} />;
}

export function DialogFooter({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={clsx('flex flex-col-reverse gap-2 sm:flex-row sm:justify-end', className)}
      {...props}
    />
  );
}

export const DialogTitle = forwardRef<
  ElementRef<typeof DialogPrimitive.Title>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={clsx('text-lg font-semibold text-ink', className)}
    {...props}
  />
));
DialogTitle.displayName = DialogPrimitive.Title.displayName;

export const DialogDescription = forwardRef<
  ElementRef<typeof DialogPrimitive.Description>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={clsx('text-sm text-faint', className)}
    {...props}
  />
));
DialogDescription.displayName = DialogPrimitive.Description.displayName;
