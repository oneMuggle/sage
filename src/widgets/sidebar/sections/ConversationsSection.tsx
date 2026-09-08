import { MessageSquare, Plus, Search } from 'lucide-react';
import { useMemo, useState } from 'react';

import { useI18n } from '../../../shared/lib/i18n';
import type { Session } from '../../../shared/lib/store';
import { SortableSessionList } from '../../session/SortableSessionList';
import { SiderSection } from '../SiderSection';

interface ConversationsSectionProps {
  sessions: Session[];
  order: string[];
  currentSessionId: string | null;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onSelect: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
  onNewSession: () => void;
  onOrderChange: (next: string[]) => void;
  /** U4': 重命名回调(透传给 SessionItem) */
  onRename?: (sessionId: string, title: string) => Promise<void>;
}

export function ConversationsSection({
  sessions,
  order,
  currentSessionId,
  collapsed,
  onToggleCollapsed,
  onSelect,
  onDelete,
  onNewSession,
  onOrderChange,
  onRename,
}: ConversationsSectionProps) {
  const { t } = useI18n();
  // U4': 标题过滤——sessions 全量已在前端内存,纯前端 filter;
  // 只影响展示,不动 dnd 持久化顺序。
  const [searchQuery, setSearchQuery] = useState('');
  const filteredSessions = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter((s) => s.title.toLowerCase().includes(q));
  }, [sessions, searchQuery]);

  return (
    <SiderSection
      sectionKey="conversations"
      label={t('sider.section.conversations')}
      icon={MessageSquare}
      collapsed={collapsed}
      onToggleCollapsed={onToggleCollapsed}
      maxHeight="50vh"
      trailing={
        <button
          type="button"
          onClick={onNewSession}
          aria-label={t('sidebar.new_chat')}
          title={t('sidebar.new_chat')}
          className="inline-flex items-center justify-center w-5 h-5 rounded text-muted hover:text-text hover:bg-bg-hover"
        >
          <Plus className="w-3.5 h-3.5" />
        </button>
      }
      render={() => (
        <div className="flex flex-col min-h-0">
          <div className="relative px-2 pb-1">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-3 h-3 text-muted pointer-events-none" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('sidebar.search_sessions')}
              aria-label={t('sidebar.search_sessions')}
              data-testid="session-search"
              className="w-full h-6 pl-6 pr-2 text-xs rounded bg-bg-hover border border-transparent focus:border-primary focus:outline-none placeholder:text-muted"
            />
          </div>
          {filteredSessions.length === 0 && searchQuery.trim() ? (
            <div className="px-3 py-4 text-xs text-text-muted text-center">
              {t('sidebar.no_match')}
            </div>
          ) : (
            <SortableSessionList
              sessions={filteredSessions}
              order={order}
              currentSessionId={currentSessionId}
              onSelect={onSelect}
              onDelete={onDelete}
              onOrderChange={onOrderChange}
              onRename={onRename}
            />
          )}
        </div>
      )}
    />
  );
}
