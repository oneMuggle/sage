// src/pages/chat/SessionSessionMenu.tsx
//
// UI 优化 2026-10-14: 合并「新对话」「新话题」「临时聊天」为一个下拉菜单。
// 触发按钮为 + 图标（MessageSquarePlus），点击弹出菜单。
// 分割线区分会话创建类操作（新对话 / 新话题）和状态切换类操作（临时聊天）。

import { MessageSquarePlus, RotateCcw } from 'lucide-react';
import type { Dispatch, SetStateAction } from 'react';
import { useEffect, useRef, useState } from 'react';

interface SessionSessionMenuProps {
  isLoading: boolean;
  hasConfig: boolean;
  currentSessionId: string | null;
  onNewTopic: () => void;
  onNewSession: () => void;
  isTempChat: boolean;
  setTempChatSessions: Dispatch<SetStateAction<ReadonlySet<string>>>;
}

export function SessionSessionMenu({
  isLoading,
  hasConfig,
  currentSessionId,
  onNewTopic,
  onNewSession,
  isTempChat,
  setTempChatSessions,
}: SessionSessionMenuProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // 点击菜单外 / Esc 收起
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

  const handleNewSession = () => {
    setOpen(false);
    onNewSession();
  };

  const handleNewTopic = () => {
    setOpen(false);
    onNewTopic();
  };

  const handleToggleTempChat = () => {
    if (!currentSessionId) return;
    setTempChatSessions((prev) => {
      const next = new Set(prev);
      if (next.has(currentSessionId)) next.delete(currentSessionId);
      else next.add(currentSessionId);
      return next;
    });
    setOpen(false);
  };

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        data-testid="session-session-menu-toggle"
        aria-label="+ 新建 / 会话操作"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 px-2 py-1 text-ui-xs border border-border rounded-radius-sm text-text-secondary hover:bg-bg-hover hover:text-text transition-colors"
      >
        <MessageSquarePlus className="w-3.5 h-3.5 shrink-0" />
      </button>
      {open && (
        <div
          className="absolute right-0 top-full z-30 mt-1 w-52 rounded-md border border-border bg-surface py-1 shadow-lg"
          data-testid="session-session-menu-dropdown"
        >
          <button
            type="button"
            className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-hover hover:text-text transition-colors"
            onClick={handleNewSession}
            data-testid="session-menu-new-session"
          >
            <MessageSquarePlus className="w-3.5 h-3.5" />
            <span className="flex-1 text-left">新对话</span>
          </button>
          <button
            type="button"
            className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-hover hover:text-text transition-colors disabled:opacity-50"
            onClick={handleNewTopic}
            disabled={isLoading || !hasConfig}
            data-testid="session-menu-new-topic"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span className="flex-1 text-left">新话题（重置上下文）</span>
          </button>
          {currentSessionId && (
            <>
              <div className="my-1 border-t border-border" aria-hidden />
              <button
                type="button"
                aria-pressed={isTempChat}
                className={`flex w-full items-center gap-2 px-3 py-1.5 text-xs transition-colors ${
                  isTempChat
                    ? 'text-warning bg-warning/10 hover:bg-warning/15'
                    : 'text-text-secondary hover:bg-bg-hover hover:text-text'
                }`}
                onClick={handleToggleTempChat}
                data-testid="session-menu-temp-chat"
              >
                <span aria-hidden="true">🕶</span>
                <span className="flex-1 text-left">临时聊天</span>
                <span className="text-ui-2xs text-muted">不记忆</span>
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
