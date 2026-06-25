import { Command } from 'cmdk';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useTheme } from '../../app/providers/useTheme';
import { useStore } from '../../shared/lib/store';

import { actionCommands, navCommands } from './commandItems';

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const navigate = useNavigate();
  const { sessions, setCurrentSessionId, createSession } = useStore();
  const { resolved, setMode } = useTheme();
  const [search, setSearch] = useState('');

  // 打开时重置搜索
  useEffect(() => {
    if (open) {
      setSearch('');
    }
  }, [open]);

  const handleNav = (path: string) => {
    navigate(path);
    onOpenChange(false);
  };

  const handleNewChat = async () => {
    const sessionId = await createSession();
    setCurrentSessionId(sessionId);
    navigate('/chat');
    onOpenChange(false);
  };

  const handleToggleTheme = () => {
    setMode(resolved === 'light' ? 'dark' : 'light');
    onOpenChange(false);
  };

  const handleOpenSession = (sessionId: string) => {
    setCurrentSessionId(sessionId);
    navigate('/chat');
    onOpenChange(false);
  };

  // 最近会话（按时间排序，取前 8 个）
  const recentSessions = [...sessions]
    .sort((a, b) => (b.last_message_at ?? b.updated_at) - (a.last_message_at ?? a.updated_at))
    .slice(0, 8);

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="命令面板"
      className="fixed top-[20%] left-1/2 -translate-x-1/2 w-full max-w-lg bg-surface border border-border rounded-radius-lg shadow-xl overflow-hidden z-50"
      shouldFilter={true}
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
        <Command.Empty className="py-6 text-center text-sm text-text-muted">
          无匹配结果
        </Command.Empty>

        {/* 导航 */}
        <Command.Group heading="导航" className="mb-1.5">
          {navCommands.map((item) => {
            const Icon = item.icon;
            return (
              <Command.Item
                key={item.path}
                value={item.label}
                onSelect={() => handleNav(item.path)}
                className="flex items-center gap-2.5 px-3 py-2 rounded-radius-sm text-sm text-text cursor-default select-none aria-selected:bg-primary/10 aria-selected:text-primary data-[disabled]:opacity-50 transition-colors"
              >
                <Icon className="w-4 h-4 text-text-muted" />
                <span>{item.label}</span>
              </Command.Item>
            );
          })}
        </Command.Group>

        {/* 操作 */}
        <Command.Group heading="操作" className="mb-1.5">
          {actionCommands.map((cmd) => {
            const Icon = cmd.icon;
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
                <div>
                  <div className="font-medium">{cmd.label}</div>
                  <div className="text-xs text-text-muted">{cmd.description}</div>
                </div>
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
      </Command.List>

      {/* 底部提示 */}
      <div className="flex items-center justify-between border-t border-border px-3 py-2 text-xs text-text-muted">
        <span>↑↓ 导航</span>
        <span>↵ 选择</span>
        <span>esc 关闭</span>
      </div>
    </Command.Dialog>
  );
}
