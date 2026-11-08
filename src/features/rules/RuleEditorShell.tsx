import { Dialog, Transition } from '@headlessui/react';
import { X } from 'lucide-react';
import { Fragment, type ReactNode } from 'react';

import { useI18n } from '../../shared/lib/i18n';
import { Button } from '../../shared/ui/Button';

export interface ShellProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer: ReactNode;
}

interface DialogFrameProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer: ReactNode;
}

function DialogBackdrop() {
  return (
    <Transition.Child
      as={Fragment}
      enter="ease-out duration-200"
      enterFrom="opacity-0"
      enterTo="opacity-100"
      leave="ease-in duration-150"
      leaveFrom="opacity-100"
      leaveTo="opacity-0"
    >
      <div className="fixed inset-0 bg-overlay" />
    </Transition.Child>
  );
}

function DialogHeader({ title, onClose }: { title: string; onClose: () => void }) {
  const { t } = useI18n();
  return (
    <div className="flex items-center justify-between border-b border-border px-5 py-3">
      <Dialog.Title as="h3" className="text-sm font-semibold text-foreground">
        {title}
      </Dialog.Title>
      <Button
        variant="ghost"
        size="icon"
        onClick={onClose}
        aria-label={t('rules.action.close')}
        data-testid="rule-editor-cancel-icon"
      >
        <X className="h-4 w-4" />
      </Button>
    </div>
  );
}

function DialogFrame({ title, onClose, children, footer }: DialogFrameProps) {
  return (
    <Transition.Child
      as={Fragment}
      enter="ease-out duration-200"
      enterFrom="opacity-0 scale-95"
      enterTo="opacity-100 scale-100"
      leave="ease-in duration-150"
      leaveFrom="opacity-100 scale-100"
      leaveTo="opacity-0 scale-95"
    >
      <Dialog.Panel
        className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl bg-surface-elevated shadow-xl dark:bg-surface"
        data-testid="rule-editor"
      >
        <DialogHeader title={title} onClose={onClose} />
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4">{children}</div>
        {footer}
      </Dialog.Panel>
    </Transition.Child>
  );
}

export function RuleEditorShell({ isOpen, onClose, title, children, footer }: ShellProps) {
  return (
    <Transition appear show={isOpen} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={onClose}>
        <DialogBackdrop />
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <DialogFrame title={title} onClose={onClose} footer={footer}>
            {children}
          </DialogFrame>
        </div>
      </Dialog>
    </Transition>
  );
}
