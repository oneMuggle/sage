import { MessageSquare, Plus, Search } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { requestMessageJump } from '../../../features/chat/messageJumpStore';
import { sessionApi } from '../../../shared/api/sessionApi';
import { useI18n } from '../../../shared/lib/i18n';
import type { Session } from '../../../shared/lib/store';
import { SessionList } from '../../session/SessionList';
import { VirtualSessionList } from '../../session/VirtualSessionList';
import { SiderSection } from '../SiderSection';

/** P1 (UI 优化方案 2026-09-13): 超过该数量的会话列表切换虚拟化渲染 ——
 *  全量 DOM 渲染在数百会话时拖慢侧栏。排序由后端 SQL 完成,前端无拖拽。 */
const VIRTUALIZE_THRESHOLD = 120;

interface ConversationsSectionProps {
  sessions: Session[];
  currentSessionId: string | null;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onSelect: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
  onNewSession: () => void;
  /** U4': 重命名回调(透传给 SessionItem) */
  onRename?: (sessionId: string, title: string) => Promise<void>;
}

/** F12: 消息搜索防抖间隔（ms）——输入停顿后才打后端 */
const MESSAGE_SEARCH_DEBOUNCE_MS = 300;

export function ConversationsSection({
  sessions,
  currentSessionId,
  collapsed,
  onToggleCollapsed,
  onSelect,
  onDelete,
  onNewSession,
  onRename,
}: ConversationsSectionProps) {
  const { t } = useI18n();
  // U4': 标题过滤——sessions 全量已在前端内存,纯前端 filter;只影响展示。
  const [searchQuery, setSearchQuery] = useState('');
  // F12: 消息内容命中计数（≥2 字符时防抖搜索,会话 id → 命中条数）
  const [messageHits, setMessageHits] = useState<Map<string, number>>(new Map());
  // 对话阅读导航 A3: 会话 id → 最新一条命中消息 id（后端按时间倒序返回，取首条）
  const [hitTargets, setHitTargets] = useState<Map<string, string>>(new Map());

  const searchInputRef = useRef<HTMLInputElement>(null);
  // R40: Ctrl+F 聚焦搜索框 —— 监听全局自定义事件
  useEffect(() => {
    const handler = () => searchInputRef.current?.focus();
    window.addEventListener('sage:focus-search', handler);
    return () => window.removeEventListener('sage:focus-search', handler);
  }, []);

  const trimmedQuery = searchQuery.trim();

  useEffect(() => {
    if (trimmedQuery.length < 2) {
      setMessageHits(new Map());
      setHitTargets(new Map());
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      sessionApi
        .searchMessages(trimmedQuery, { limit: 50 })
        .then((results) => {
          if (cancelled) return;
          const hits = new Map<string, number>();
          const targets = new Map<string, string>();
          for (const r of results) {
            hits.set(r.sessionId, (hits.get(r.sessionId) ?? 0) + 1);
            if (!targets.has(r.sessionId)) targets.set(r.sessionId, r.messageId);
          }
          setMessageHits(hits);
          setHitTargets(targets);
        })
        .catch(() => {
          // 搜索失败静默降级为纯标题过滤
          if (!cancelled) {
            setMessageHits(new Map());
            setHitTargets(new Map());
          }
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

  // 对话阅读导航 A3: 搜索态下点开有消息命中的会话 → 先登记定位请求再切会话，
  // 消息加载完成后 MessageList 自动滚到命中消息并高亮（对标"搜索命中直达"）。
  // 第二轮 B3：请求带上搜索词，定位后在消息正文里高亮命中。
  const handleSelect = useCallback(
    (sessionId: string) => {
      const target = trimmedQuery.length >= 2 ? hitTargets.get(sessionId) : undefined;
      if (target) requestMessageJump({ messageId: target, highlightQuery: trimmedQuery });
      onSelect(sessionId);
    },
    [hitTargets, onSelect, trimmedQuery],
  );

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
              ref={searchInputRef}
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
          ) : displaySessions.length > VIRTUALIZE_THRESHOLD ? (
            <VirtualSessionList
              sessions={displaySessions}
              currentSessionId={currentSessionId}
              onSelect={handleSelect}
              onDelete={onDelete}
              onRename={onRename}
              messageHitsBySession={messageHits}
              maxHeight="50vh"
            />
          ) : (
            <SessionList
              sessions={displaySessions}
              currentSessionId={currentSessionId}
              onSelect={handleSelect}
              onDelete={onDelete}
              onRename={onRename}
              messageHitsBySession={messageHits}
            />
          )}
        </div>
      )}
    />
  );
}
