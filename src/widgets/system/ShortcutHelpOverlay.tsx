// src/widgets/system/ShortcutHelpOverlay.tsx
//
// U18 (round4 批次 E): 快捷键帮助覆盖层。数据源 src/shared/lib/shortcuts.ts。
// 打开方式：任意非输入焦点下按 Shift+/（即 '?'）；Esc / 点击背景关闭。

import { useEffect } from 'react';

import { SHORTCUT_GROUPS } from '../../shared/lib/shortcuts';

interface ShortcutHelpOverlayProps {
  open: boolean;
  onClose: () => void;
}

export function ShortcutHelpOverlay({ open, onClose }: ShortcutHelpOverlayProps) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      data-testid="shortcut-help-overlay"
      className="fixed inset-0 z-50 flex items-center justify-center bg-overlay"
      onClick={onClose}
    >
      <div
        className="bg-surface-elevated border border-border rounded-radius-md shadow-lg max-w-lg w-full mx-4 max-h-[80vh] flex flex-col"
        role="dialog"
        aria-label="快捷键帮助"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <h2 className="text-sm font-semibold text-text">键盘快捷键</h2>
          <button
            className="text-text-secondary hover:text-text text-sm px-1"
            aria-label="关闭快捷键帮助"
            onClick={onClose}
          >
            ✕
          </button>
        </div>
        <div className="overflow-y-auto px-4 py-3 flex flex-col gap-4">
          {SHORTCUT_GROUPS.map((group) => (
            <section key={group.group}>
              <h3 className="text-xs font-medium text-text-secondary mb-1.5">{group.group}</h3>
              <ul className="flex flex-col gap-1">
                {group.items.map((item) => (
                  <li key={item.keys} className="flex items-center gap-3 text-sm">
                    <kbd className="shrink-0 min-w-[9rem] text-left px-1.5 py-0.5 rounded bg-bg-subtle border border-border text-xs font-mono text-text-secondary">
                      {item.keys}
                    </kbd>
                    <span className="text-text">{item.description}</span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
