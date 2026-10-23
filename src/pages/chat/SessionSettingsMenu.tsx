// src/pages/chat/SessionSettingsMenu.tsx
//
// UI 优化 2026-10-14: 收纳 PermissionModeSwitch + ContextMeter 到一个齿轮浮层。
// 触发按钮为 Settings 图标（lucide-react），点击弹出浮层展示两个会话级设置。
// 避免常态显示两个独立控件占用顶栏空间。

import { Settings } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { ContextMeter } from '../../widgets/chat/ContextMeter';
import { PermissionModeSwitch } from '../../widgets/chat/PermissionModeSwitch';

interface SessionSettingsMenuProps {
  sessionId: string | null;
}

export function SessionSettingsMenu({ sessionId }: SessionSettingsMenuProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // 点击浮层外 / Esc 收起
  useEffect(() => {
    if (!open) return;
    const onDocMouseDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDocMouseDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onDocMouseDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        data-testid="session-settings-menu-toggle"
        aria-label="会话设置"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 px-2 py-1 text-ui-xs border border-border rounded-radius-sm text-text-secondary hover:bg-bg-hover hover:text-text transition-colors"
      >
        <Settings className="w-3.5 h-3.5 shrink-0" />
      </button>
      {open && (
        <div
          className="absolute right-0 top-full z-30 mt-1 w-56 rounded-md border border-border bg-surface py-2 px-3 shadow-lg space-y-2"
          data-testid="session-settings-menu-dropdown"
          onClick={(e) => e.stopPropagation()}
        >
          <div>
            <div className="text-ui-2xs text-muted mb-1">权限模式</div>
            <PermissionModeSwitch sessionId={sessionId} placement="bottom" />
          </div>
          <div className="border-t border-border" aria-hidden />
          <div>
            <div className="text-ui-2xs text-muted mb-1">上下文用量</div>
            <ContextMeter sessionId={sessionId} placement="bottom" />
          </div>
        </div>
      )}
    </div>
  );
}
