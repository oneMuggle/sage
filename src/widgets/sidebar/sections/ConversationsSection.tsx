import { MessageSquare, Plus, Search, Trash2 } from 'lucide-react';
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

/** 自动归档天数偏好（localStorage 持久化；0=关闭）。 */
const AUTO_ARCHIVE_KEY = 'sage:session-auto-archive-days';

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
  /** 自动归档 sweep / 清空归档后的会话列表刷新回调 */
  onRefreshSessions?: () => void;
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
  onRefreshSessions,
}: ConversationsSectionProps) {
  const { t } = useI18n();
  // U4': 标题过滤——sessions 全量已在前端内存,纯前端 filter;只影响展示。
  const [searchQuery, setSearchQuery] = useState('');
  // F12: 消息内容命中计数（≥2 字符时防抖搜索,会话 id → 命中条数）
  const [messageHits, setMessageHits] = useState<Map<string, number>>(new Map());
  // 对话阅读导航 A3: 会话 id → 最新一条命中消息 id（后端按时间倒序返回，取首条）
  const [hitTargets, setHitTargets] = useState<Map<string, string>>(new Map());

  const searchInputRef = useRef<HTMLInputElement>(null);
  // R51: 归档会话显示切换
  const [showArchived, setShowArchived] = useState(false);
  // 对标 ZCode taskAutoArchive：自动归档天数偏好（0=关闭），localStorage 持久化。
  const [autoArchiveDays, setAutoArchiveDays] = useState(() =>
    Number(localStorage.getItem(AUTO_ARCHIVE_KEY) ?? 0),
  );
  const [purging, setPurging] = useState(false);
  // R40: Ctrl+F 聚焦搜索框 —— 监听全局自定义事件
  useEffect(() => {
    const handler = () => searchInputRef.current?.focus();
    window.addEventListener('sage:focus-search', handler);
    return () => window.removeEventListener('sage:focus-search', handler);
  }, []);

  const trimmedQuery = searchQuery.trim();
  // R51: 归档过滤 —— 默认隐藏已归档会话

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
    const base = showArchived ? sessions : sessions.filter((s) => !s.is_archived);
    const q = trimmedQuery.toLowerCase();
    if (!q) return base;
    // 标题匹配优先;消息内容命中的会话（标题不匹配也）并入展示
    const titleMatches = base.filter((s) => s.title.toLowerCase().includes(q));
    const seen = new Set(titleMatches.map((s) => s.id));
    const messageMatches = base.filter((s) => !seen.has(s.id) && messageHits.has(s.id));
    return [...titleMatches, ...messageMatches];
  }, [sessions, trimmedQuery, messageHits, showArchived]);

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

  // 自动归档 sweep：偏好非关闭时，侧栏挂载/偏好变更即归档过期会话并刷新。
  const sweep = useCallback(
    (days: number) => {
      if (days <= 0) return;
      void sessionApi
        .archiveStale(days)
        .then(() => onRefreshSessions?.())
        .catch(() => {
          /* sweep 失败静默，下次挂载重试 */
        });
    },
    [onRefreshSessions],
  );

  useEffect(() => {
    localStorage.setItem(AUTO_ARCHIVE_KEY, String(autoArchiveDays));
    sweep(autoArchiveDays);
  }, [autoArchiveDays, sweep]);

  const handlePurgeArchived = useCallback(() => {
    if (!window.confirm('永久删除全部归档会话（含消息）？此操作不可撤销。')) return;
    setPurging(true);
    void sessionApi
      .purgeArchived()
      .then(() => onRefreshSessions?.())
      .catch(() => {
        /* purge 失败静默，列表下次刷新恢复 */
      })
      .finally(() => setPurging(false));
  }, [onRefreshSessions]);

  const archivedCount = useMemo(
    () => sessions.filter((s) => s.is_archived).length,
    [sessions],
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
          <div className="relative px-2 pb-1 flex items-center gap-1">
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
            <button
              type="button"
              data-testid="toggle-archived"
              onClick={() => setShowArchived((v) => !v)}
              className={`text-[11px] whitespace-nowrap ${showArchived ? 'text-primary' : 'text-muted hover:text-text'}`}
            >
              {showArchived ? '隐藏归档' : '归档'}
            </button>
          </div>
          {showArchived && (
            <div
              className="px-2 pb-1 flex items-center gap-2 text-[11px] text-muted"
              data-testid="archived-toolbar"
            >
              <label className="whitespace-nowrap flex items-center gap-1">
                自动归档
                <select
                  data-testid="auto-archive-select"
                  value={autoArchiveDays}
                  onChange={(e) => setAutoArchiveDays(Number(e.target.value))}
                  className="h-5 rounded bg-bg-hover border border-transparent focus:border-primary focus:outline-none text-[11px]"
                >
                  <option value={0}>关闭</option>
                  <option value={3}>3 天</option>
                  <option value={7}>7 天</option>
                  <option value={14}>14 天</option>
                  <option value={30}>30 天</option>
                </select>
              </label>
              <button
                type="button"
                data-testid="purge-archived"
                disabled={purging || archivedCount === 0}
                onClick={handlePurgeArchived}
                className="ml-auto inline-flex items-center gap-1 whitespace-nowrap hover:text-error disabled:opacity-40 disabled:hover:text-muted"
                title="永久删除全部归档会话（含消息）"
              >
                <Trash2 className="w-3 h-3" />
                清空全部归档
              </button>
            </div>
          )}
          {sessions.length === 0 ? (
            <div className="px-3 py-6 text-xs text-text-muted text-center space-y-2" data-testid="sessions-empty">
              <p>尚无会话</p>
              <button
                type="button"
                data-testid="sessions-empty-new"
                onClick={onNewSession}
                className="text-primary hover:underline"
              >
                + 新建会话
              </button>
            </div>
          ) : displaySessions.length === 0 && searchQuery.trim() ? (
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
