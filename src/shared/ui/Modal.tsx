import { Dialog, Transition } from '@headlessui/react';
import { X } from 'lucide-react';
import { Fragment, ReactNode } from 'react';

import { Button } from './Button';

export interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  footer?: ReactNode;
  /**
   * 面板宽度档位 —— 默认 `'md'`（`max-w-md`）。
   *
   * 历史上本组件宽度写死 `'md'`，导致报告类宽内容（Markdown 正文 + 统计块）
   * 只能另起炉灶复制一份弹窗（见 `widgets/session/ArchivesModal.tsx`）。
   * 加档位后，宽内容可直接复用，存量调用方不传即保持原样。
   */
  size?: 'md' | 'lg' | 'xl';
}

/** 宽度档位 → Tailwind 类名。 */
const SIZE_CLASSES: Record<NonNullable<ModalProps['size']>, string> = {
  md: 'max-w-md',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
};

export function Modal({ isOpen, onClose, title, children, footer, size = 'md' }: ModalProps) {
  return (
    <Transition appear show={isOpen} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={onClose}>
        {/* 背景遮罩 */}
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

        <div className="fixed inset-0 overflow-y-auto">
          <div className="flex min-h-full items-center justify-center p-4">
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
                className={`w-full ${SIZE_CLASSES[size]} transform overflow-hidden rounded-xl bg-surface-elevated dark:bg-surface shadow-xl transition-all`}
              >
                {/* 头部 */}
                {title && (
                  <div className="flex items-center justify-between px-6 py-4 border-b border-border">
                    <Dialog.Title as="h3" className="text-lg font-semibold">
                      {title}
                    </Dialog.Title>
                    <Button variant="ghost" size="icon" onClick={onClose}>
                      <X className="w-5 h-5" />
                    </Button>
                  </div>
                )}

                {/* 内容 */}
                <div className="px-6 py-4">{children}</div>

                {/* 底部 */}
                {footer && <div className="px-6 py-4 border-t border-border">{footer}</div>}
              </Dialog.Panel>
            </Transition.Child>
          </div>
        </div>
      </Dialog>
    </Transition>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatModalDialogSummary(
  isOpen: boolean,
  hasTitle = true,
  hasFooter = false,
): string {
  return `open=${Boolean(isOpen)} · title=${Boolean(hasTitle)} · footer=${Boolean(hasFooter)}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatModalDialogJson(isOpen: boolean, hasTitle = true, hasFooter = false): string {
  return JSON.stringify({
    isOpen: Boolean(isOpen),
    hasTitle: Boolean(hasTitle),
    hasFooter: Boolean(hasFooter),
  });
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditModalGovernance(): string {
  return JSON.stringify({
    module: 'ui-modal',
    phase: 'P184',
    audited: true,
  });
}
