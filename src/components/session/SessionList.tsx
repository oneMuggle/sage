import { Plus, Search } from 'lucide-react';
import { useState } from 'react';

import type { Session } from '../../shared/lib/store';
import { Button } from '../common/Button';

import { SessionItem } from './SessionItem';

interface SessionListProps {
  sessions: Session[];
  currentSessionId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

export function SessionList({
  sessions,
  currentSessionId,
  onSelect,
  onNew,
  onDelete,
}: SessionListProps) {
  const [searchQuery, setSearchQuery] = useState('');

  const filteredSessions = sessions.filter((s) =>
    s.title.toLowerCase().includes(searchQuery.toLowerCase()),
  );

  const pinned = filteredSessions.filter((s) => s.is_pinned);
  const unpinned = filteredSessions.filter((s) => !s.is_pinned);

  return (
    <div className="flex flex-col h-full">
      {/* 搜索 */}
      <div className="p-3 border-b border-border">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
          <input
            type="text"
            placeholder="搜索会话..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="
              w-full pl-9 pr-3 py-2 rounded-lg
              bg-bg-subtle
              border-none focus:outline-none focus:ring-2 focus:ring-primary/50
              text-sm
            "
          />
        </div>
      </div>

      {/* 新建按钮 */}
      <div className="p-3">
        <Button variant="primary" className="w-full" onClick={onNew}>
          <Plus className="w-4 h-4 mr-2" />
          新对话
        </Button>
      </div>

      {/* 会话列表 */}
      <div className="flex-1 overflow-y-auto">
        {/* 置顶会话 */}
        {pinned.length > 0 && (
          <div className="px-3 py-1">
            <div className="text-xs text-muted px-2 mb-1">置顶</div>
            {pinned.map((session) => (
              <SessionItem
                key={session.id}
                session={session}
                isActive={session.id === currentSessionId}
                onSelect={() => onSelect(session.id)}
                onDelete={() => onDelete(session.id)}
              />
            ))}
          </div>
        )}

        {/* 普通会话 */}
        {unpinned.length > 0 && (
          <div className="px-3 py-1">
            {pinned.length > 0 && <div className="text-xs text-muted px-2 mb-1">最近</div>}
            {unpinned.map((session) => (
              <SessionItem
                key={session.id}
                session={session}
                isActive={session.id === currentSessionId}
                onSelect={() => onSelect(session.id)}
                onDelete={() => onDelete(session.id)}
              />
            ))}
          </div>
        )}

        {/* 空状态 */}
        {filteredSessions.length === 0 && (
          <div className="text-center text-muted py-8 text-sm">
            {searchQuery ? '未找到匹配的会话' : '暂无会话'}
          </div>
        )}
      </div>
    </div>
  );
}
