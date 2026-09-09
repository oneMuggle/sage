import { MessageSquare, Plus, Search } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { sessionApi } from '../../../shared/api/sessionApi';
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

/** F12: 消息搜索防抖间隔（ms）——输入停顿后才打后端 */
const MESSAGE_SEARCH_DEBOUNCE_MS = 300;

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
  // F12: 消息内容命中计数（≥2 字符时防抖搜索,会话 id → 命中条数）
  const [messageHits, setMessageHits] = useState<Map<string, number>>(new Map());

  const trimmedQuery = searchQuery.trim();

  useEffect(() => {
    if (trimmedQuery.length < 2) {
      setMessageHits(new Map());
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      sessionApi
        .searchMessages(trimmedQuery, { limit: 50 })
        .then((results) => {
          if (cancelled) return;
          const hits = new Map<string, number>();
          for (const r of results) hits.set(r.sessionId, (hits.get(r.sessionId) ?? 0) + 1);
          setMessageHits(hits);
        })
        .catch(() => {
          // 搜索失败静默降级为纯标题过滤
          if (!cancelled) setMessageHits(new Map());
        });
    }, MESSAGE_SEARCH_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [trimmedQuery]);

  const displaySessions = useMemo(() => {
    const q = trimmedQuery.toLowerCase();
    if (!q) return sessions;
    // 标题匹配优先;消息内容命中的会话（标题不匹配也）并入展示
    const titleMatches = sessions.filter((s) => s.title.toLowerCase().includes(q));
    const seen = new Set(titleMatches.map((s) => s.id));
    const messageMatches = sessions.filter((s) => !seen.has(s.id) && messageHits.has(s.id));
    return [...titleMatches, ...messageMatches];
  }, [sessions, trimmedQuery, messageHits]);

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
          {displaySessions.length === 0 && searchQuery.trim() ? (
            <div className="px-3 py-4 text-xs text-text-muted text-center">
              {t('sidebar.no_match')}
            </div>
          ) : (
            <SortableSessionList
              sessions={displaySessions}
              order={order}
              currentSessionId={currentSessionId}
              onSelect={onSelect}
              onDelete={onDelete}
              onOrderChange={onOrderChange}
              onRename={onRename}
              messageHitsBySession={messageHits}
            />
          )}
        </div>
      )}
    />
  );
}
