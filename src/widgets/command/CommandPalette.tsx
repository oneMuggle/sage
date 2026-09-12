import { Command } from 'cmdk';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useTheme } from '../../app/providers/useTheme';
import { backendRequest } from '../../shared/api/backendRequest';
import { useStore } from '../../shared/lib/store';

import { actionCommands, navCommands } from './commandItems';

// ⌘1-9 快捷键跳转 (U6 from OpenWorker)
const KEYBOARD_SHORTCUTS = ['1', '2', '3', '4', '5', '6', '7', '8', '9'];

/** P1-3.7: 全局搜索返回类型（后端 /api/v1/search/global）。 */
interface GlobalSearchResult {
  sessions?: Array<{ id: string; title: string; updated_at: number; message_count: number }>;
  memories?: Array<{
    id: string;
    content: string;
    memory_type: string;
    importance: number;
    tags: string[];
  }>;
  knowledge?: Array<{ path: string; title: string; snippet: string }>;
}

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const navigate = useNavigate();
  const { sessions, setCurrentSessionId, createSession } = useStore();
  const { resolved, setMode } = useTheme();
  const [search, setSearch] = useState('');
  const [globalResults, setGlobalResults] = useState<GlobalSearchResult | null>(null);
  const [searching, setSearching] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // 打开时重置搜索
  useEffect(() => {
    if (open) {
      setSearch('');
      setGlobalResults(null);
    }
  }, [open]);

  // P1-3.7: 当搜索词 >= 2 字符时，debounce 300ms 调用后端全局搜索
  useEffect(() => {
    if (search.length < 2) {
      setGlobalResults(null);
      return;
    }

    // Cancel in-flight request
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const timer = setTimeout(async () => {
      setSearching(true);
      try {
        const params = new URLSearchParams({ q: search, limit: '10' });
        const result = await backendRequest<GlobalSearchResult>({
          path: `/api/v1/search/global?${params}`,
        });
        if (!controller.signal.aborted) {
          setGlobalResults(result);
        }
      } catch {
        // Backend unavailable — silently degrade to command-only mode
        if (!controller.signal.aborted) {
          setGlobalResults(null);
        }
      } finally {
        if (!controller.signal.aborted) {
          setSearching(false);
        }
      }
    }, 300);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [search]);

  const handleNav = useCallback(
    (path: string) => {
      navigate(path);
      onOpenChange(false);
    },
    [navigate, onOpenChange],
  );

  const handleNewChat = useCallback(async () => {
    const sessionId = await createSession();
    setCurrentSessionId(sessionId);
    navigate('/chat');
    onOpenChange(false);
  }, [createSession, setCurrentSessionId, navigate, onOpenChange]);

  const handleToggleTheme = useCallback(() => {
    setMode(resolved === 'light' ? 'dark' : 'light');
    onOpenChange(false);
  }, [setMode, resolved, onOpenChange]);

  const handleOpenSession = useCallback(
    (sessionId: string) => {
      setCurrentSessionId(sessionId);
      navigate('/chat');
      onOpenChange(false);
    },
    [setCurrentSessionId, navigate, onOpenChange],
  );

  // 最近会话（按时间排序，取前 8 个）
  const recentSessions = [...sessions]
    .sort((a, b) => (b.last_message_at ?? b.updated_at) - (a.last_message_at ?? a.updated_at))
    .slice(0, 8);

  // ⌘1-9 快捷键跳转 (U6 from OpenWorker)
  useEffect(() => {
    if (!open) return;

    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && KEYBOARD_SHORTCUTS.includes(e.key)) {
        e.preventDefault();
        const index = parseInt(e.key) - 1;

        // 导航命令优先
        if (index < navCommands.length) {
          handleNav(navCommands[index].path);
          return;
        }

        // 然后是操作命令
        const actionIndex = index - navCommands.length;
        if (actionIndex < actionCommands.length) {
          const cmd = actionCommands[actionIndex];
          if (cmd.id === 'new-chat') handleNewChat();
          else if (cmd.id === 'toggle-theme') handleToggleTheme();
          return;
        }

        // 最后是最近会话
        const sessionIndex = index - navCommands.length - actionCommands.length;
        if (sessionIndex < recentSessions.length) {
          handleOpenSession(recentSessions[sessionIndex].id);
        }
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, recentSessions, handleNav, handleNewChat, handleToggleTheme, handleOpenSession]);

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="命令面板"
      className="fixed top-[20%] left-1/2 -translate-x-1/2 w-full max-w-lg bg-surface border border-border rounded-radius-lg shadow-xl overflow-hidden z-50 animate-cmdk-enter"
      shouldFilter={search.length < 2}
    >
      <div className="flex items-center border-b border-border px-3">
        <Command.Input
          value={search}
          onValueChange={setSearch}
          placeholder="输入命令或搜索..."
          className="w-full h-12 bg-transparent text-sm text-text placeholder:text-text-muted outline-none"
          autoFocus
        />
      </div>
      <Command.List className="max-h-80 overflow-y-auto p-1.5">
        {search.length < 2 && (
          <Command.Empty className="py-6 text-center text-sm text-text-muted">
            无匹配结果
          </Command.Empty>
        )}

        {/* 命令模式（搜索词 < 2 字符）：导航 + 操作 + 最近会话 */}
        {search.length < 2 && (
          <>
            {/* 导航 */}
            <Command.Group heading="导航" className="mb-1.5">
              {navCommands.map((item, index) => {
                const Icon = item.icon;
                const shortcut = KEYBOARD_SHORTCUTS[index];
                return (
                  <Command.Item
                    key={item.path}
                    value={item.label}
                    onSelect={() => handleNav(item.path)}
                    className="flex items-center gap-2.5 px-3 py-2 rounded-radius-sm text-sm text-text cursor-default select-none aria-selected:bg-primary/10 aria-selected:text-primary data-[disabled]:opacity-50 transition-colors"
                  >
                    <Icon className="w-4 h-4 text-text-muted" />
                    <span className="flex-1">{item.label}</span>
                    {shortcut && (
                      <kbd className="ml-auto text-xs text-faint bg-bg-muted px-1.5 py-0.5 rounded border border-line">
                        ⌘{shortcut}
                      </kbd>
                    )}
                  </Command.Item>
                );
              })}
            </Command.Group>

            {/* 操作 */}
            <Command.Group heading="操作" className="mb-1.5">
              {actionCommands.map((cmd, index) => {
                const Icon = cmd.icon;
                const shortcut = KEYBOARD_SHORTCUTS[navCommands.length + index];
                return (
                  <Command.Item
                    key={cmd.id}
                    value={`${cmd.label} ${cmd.description}`}
                    onSelect={() => {
                      if (cmd.id === 'new-chat') handleNewChat();
                      else if (cmd.id === 'toggle-theme') handleToggleTheme();
                    }}
                    className="flex items-center gap-2.5 px-3 py-2 rounded-radius-sm text-sm text-text cursor-default select-none aria-selected:bg-primary/10 aria-selected:text-primary data-[disabled]:opacity-50 transition-colors"
                  >
                    <Icon className="w-4 h-4 text-text-muted" />
                    <div className="flex-1">
                      <div className="font-medium">{cmd.label}</div>
                      <div className="text-xs text-text-muted">{cmd.description}</div>
                    </div>
                    {shortcut && (
                      <kbd className="ml-auto text-xs text-faint bg-bg-muted px-1.5 py-0.5 rounded border border-line">
                        ⌘{shortcut}
                      </kbd>
                    )}
                  </Command.Item>
                );
              })}
            </Command.Group>

            {/* 最近会话 */}
            {recentSessions.length > 0 && (
              <Command.Group heading="最近会话">
                {recentSessions.map((session) => (
                  <Command.Item
                    key={session.id}
                    value={session.title}
                    onSelect={() => handleOpenSession(session.id)}
                    className="flex items-center gap-2.5 px-3 py-2 rounded-radius-sm text-sm text-text cursor-default select-none aria-selected:bg-primary/10 aria-selected:text-primary data-[disabled]:opacity-50 transition-colors"
                  >
                    <span className="truncate">{session.title || '新对话'}</span>
                    <span className="ml-auto text-xs text-text-muted">
                      {session.message_count} 条消息
                    </span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
          </>
        )}

        {/* P1-3.7: 全局搜索结果（搜索词 >= 2 字符时显示） */}
        {search.length >= 2 && searching && (
          <Command.Item
            disabled
            value="searching"
            className="py-4 text-center text-sm text-text-muted"
          >
            搜索中…
          </Command.Item>
        )}
        {search.length >= 2 && !searching && globalResults && (
          <>
            {globalResults.sessions && globalResults.sessions.length > 0 && (
              <Command.Group heading="会话">
                {globalResults.sessions.map((s) => (
                  <Command.Item
                    key={s.id}
                    value={`session-${s.id}-${s.title}`}
                    onSelect={() => handleOpenSession(s.id)}
                    className="flex items-center gap-2.5 px-3 py-2 rounded-radius-sm text-sm text-text cursor-default select-none aria-selected:bg-primary/10 aria-selected:text-primary data-[disabled]:opacity-50 transition-colors"
                  >
                    <span className="truncate">{s.title || '新对话'}</span>
                    <span className="ml-auto text-xs text-text-muted">
                      {s.message_count} 条消息
                    </span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
            {globalResults.memories && globalResults.memories.length > 0 && (
              <Command.Group heading="记忆">
                {globalResults.memories.map((m) => (
                  <Command.Item
                    key={m.id}
                    value={`memory-${m.id}-${m.content.slice(0, 50)}`}
                    onSelect={() => {
                      navigate('/memory');
                      onOpenChange(false);
                    }}
                    className="flex items-center gap-2.5 px-3 py-2 rounded-radius-sm text-sm text-text cursor-default select-none aria-selected:bg-primary/10 aria-selected:text-primary data-[disabled]:opacity-50 transition-colors"
                  >
                    <span className="flex-1 truncate">{m.content.slice(0, 80)}</span>
                    <span className="text-xs text-text-muted">{m.memory_type}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
            {globalResults.knowledge && globalResults.knowledge.length > 0 && (
              <Command.Group heading="知识库">
                {globalResults.knowledge.map((k) => (
                  <Command.Item
                    key={k.path}
                    value={`knowledge-${k.path}-${k.title}`}
                    onSelect={() => {
                      navigate('/knowledge');
                      onOpenChange(false);
                    }}
                    className="flex items-center gap-2.5 px-3 py-2 rounded-radius-sm text-sm text-text cursor-default select-none aria-selected:bg-primary/10 aria-selected:text-primary data-[disabled]:opacity-50 transition-colors"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="truncate">{k.title || k.path}</div>
                      <div className="text-xs text-text-muted truncate">{k.snippet}</div>
                    </div>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
            {(!globalResults.sessions?.length &&
              !globalResults.memories?.length &&
              !globalResults.knowledge?.length) && (
              <div className="py-6 text-center text-sm text-text-muted">无匹配结果</div>
            )}
          </>
        )}
      </Command.List>

      {/* 底部提示 */}
      <div className="flex items-center justify-between border-t border-border px-3 py-2 text-xs text-text-muted">
        <span>↑↓ 导航</span>
        <span>⌘1-9 跳转</span>
        <span>↵ 选择</span>
        <span>esc 关闭</span>
      </div>
    </Command.Dialog>
  );
}
