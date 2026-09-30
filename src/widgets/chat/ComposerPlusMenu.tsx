// src/widgets/chat/ComposerPlusMenu.tsx
//
// UX-IA R1 批次 C（docs/plans/2026-09-29_ux-ia-round1-batch-c.md）：
// 输入框「+」工具菜单。对标 ChatGPT「+」/ Claude 工具菜单：把原先散落在
// textarea 右侧的一排图标（插图 / 附件 / 知识库 / 定时）收进一个入口，并补上
// 「@ 引用」「/ 命令」两个原本只能靠记忆触发的能力，降低发现成本。
// 菜单只负责分发；每一项的实际行为由 InputCard 传入，行为与改前一致。

import { Plus } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';

export interface ComposerPlusMenuItem {
  key: string;
  label: string;
  icon: ReactNode;
  /** 右侧快捷提示（如 "@"、"/"） */
  hint?: string;
  disabled?: boolean;
  onSelect: () => void;
}

interface ComposerPlusMenuProps {
  items: ComposerPlusMenuItem[];
  disabled?: boolean;
}

export function ComposerPlusMenu({ items, disabled = false }: ComposerPlusMenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown, true);
    };
  }, [open]);

  if (items.length === 0) return null;

  return (
    <div ref={rootRef} className="relative flex-shrink-0">
      <button
        type="button"
        data-testid="composer-plus"
        aria-label="添加内容与工具"
        aria-haspopup="menu"
        aria-expanded={open}
        title="添加内容与工具"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className="w-7 h-7 flex items-center justify-center rounded-radius-sm hover:bg-bg-hover text-muted hover:text-text transition-colors disabled:opacity-50"
      >
        <Plus className={`w-4 h-4 transition-transform ${open ? 'rotate-45' : ''}`} />
      </button>
      {open && (
        <div
          role="menu"
          data-testid="composer-plus-menu"
          className="absolute bottom-full left-0 mb-2 w-56 py-1 bg-surface border border-border rounded-radius-md shadow-lg z-30"
        >
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              role="menuitem"
              data-testid={`composer-plus-item-${item.key}`}
              disabled={item.disabled}
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
              className="w-full flex items-center gap-2.5 px-3 py-1.5 text-sm text-text-secondary hover:bg-bg-hover hover:text-text disabled:opacity-40 disabled:hover:bg-transparent transition-colors"
            >
              <span className="w-4 h-4 flex items-center justify-center">{item.icon}</span>
              <span className="flex-1 text-left">{item.label}</span>
              {item.hint && <span className="text-xs text-muted font-mono">{item.hint}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
