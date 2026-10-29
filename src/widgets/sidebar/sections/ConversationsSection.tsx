import { MessageSquare, Plus, Search, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
<<<<<<< HEAD
=======
import { toast } from 'sonner';
>>>>>>> origin/main

import { requestMessageJump } from '../../../features/chat/messageJumpStore';
import { sessionApi } from '../../../shared/api/sessionApi';
import { useI18n } from '../../../shared/lib/i18n';
import type { Session } from '../../../shared/lib/store';
import { confirmDialog } from '../../../shared/ui/ConfirmDialog/confirmService';
import { SessionList } from '../../session/SessionList';
import { VirtualSessionList } from '../../session/VirtualSessionList';
import { SiderSection } from '../SiderSection';

/** P1 (UI 优化方案 2026-09-13): 超过该数量的会话列表切换虚拟化渲染 ——
 *  全量 DOM 渲染在数百会话时拖慢侧栏。排序由后端 SQL 完成,前端无拖拽。 */
const VIRTUALIZE_THRESHOLD = 120;

<<<<<<< HEAD
=======
/** 归档视图分页大小（与后端默认 limit 对齐）。 */
const ARCHIVED_PAGE_SIZE = 100;

/** 距离底部多少像素时触发下一页加载。 */
const LOAD_MORE_THRESHOLD_PX = 240;

>>>>>>> origin/main
/** 自动归档天数偏好（localStorage 持久化；0=关闭）。 */
const AUTO_ARCHIVE_KEY = 'sage:session-auto-archive-days';

export interface ConversationsSectionAuditInput {
  totalCount: number;
  displayCount: number;
  archivedCount: number;
  showArchived: boolean;
  hasQuery: boolean;
  virtualized: boolean;
}

export function formatConversationsSectionAuditSnapshot(
  input: ConversationsSectionAuditInput,
): string {
  return `total=${input.totalCount}|display=${input.displayCount}|archived=${input.archivedCount}|showArchived=${input.showArchived ? 1 : 0}|query=${input.hasQuery ? 1 : 0}|virt=${input.virtualized ? 1 : 0}`;
}

<<<<<<< HEAD
export function formatConversationsSectionAuditJson(
  input: ConversationsSectionAuditInput,
): string {
=======
export function formatConversationsSectionAuditJson(input: ConversationsSectionAuditInput): string {
>>>>>>> origin/main
  return JSON.stringify({
    totalCount: input.totalCount,
    displayCount: input.displayCount,
    archivedCount: input.archivedCount,
    showArchived: input.showArchived,
    hasQuery: input.hasQuery,
    virtualized: input.virtualized,
  });
}

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
<<<<<<< HEAD
=======
  /** 手动归档（失败时上层已 toast，本组件只需吞掉异常） */
  onArchiveSession?: (sessionId: string) => Promise<void>;
  /** 恢复归档 */
  onUnarchiveSession?: (sessionId: string) => Promise<void>;
  /** 滚动触底加载下一页（默认视图分页） */
  onLoadMoreSessions?: () => void;
  sessionsHasMore?: boolean;
  sessionsLoadingMore?: boolean;
>>>>>>> origin/main
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
<<<<<<< HEAD
=======
  onArchiveSession,
  onUnarchiveSession,
  onLoadMoreSessions,
  sessionsHasMore = false,
  sessionsLoadingMore = false,
>>>>>>> origin/main
}: ConversationsSectionProps) {
  const { t } = useI18n();
  // U4': 标题过滤——sessions 全量已在前端内存,纯前端 filter;只影响展示。
  const [searchQuery, setSearchQuery] = useState('');
  // F12: 消息内容命中计数（≥2 字符时防抖搜索,会话 id → 命中条数）
  const [messageHits, setMessageHits] = useState<Map<string, number>>(new Map());
  // 对话阅读导航 A3: 会话 id → 最新一条命中消息 id（后端按时间倒序返回，取首条）
  const [hitTargets, setHitTargets] = useState<Map<string, string>>(new Map());

  const searchInputRef = useRef<HTMLInputElement>(null);
<<<<<<< HEAD
  // R51: 归档会话显示切换
  const [showArchived, setShowArchived] = useState(false);
=======
  // R51: 归档会话显示切换（归档列表按需拉取，不污染全局 sessions）
  const [showArchived, setShowArchived] = useState(false);
  const [archivedSessions, setArchivedSessions] = useState<Session[] | null>(null);
  const [archivedLoading, setArchivedLoading] = useState(false);
  const [archivedHasMore, setArchivedHasMore] = useState(false);
  // 会话列表唯一的滚动容器（搜索栏/工具条固定在面板上方，不参与滚动）
  const listScrollRef = useRef<HTMLDivElement>(null);
>>>>>>> origin/main
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
<<<<<<< HEAD
=======

  // 归档列表按需拉取：打开归档视图时重新拉第一页，避免自动归档后视图过期。
  const loadArchived = useCallback(async (offset = 0) => {
    setArchivedLoading(true);
    try {
      const page = await sessionApi.list({
        archived: true,
        limit: ARCHIVED_PAGE_SIZE,
        offset,
      });
      setArchivedSessions((prev) => {
        if (offset === 0) return page;
        const base = prev ?? [];
        const seen = new Set(base.map((s) => s.id));
        return [...base, ...page.filter((s) => !seen.has(s.id))];
      });
      setArchivedHasMore(page.length === ARCHIVED_PAGE_SIZE);
    } catch {
      // 归档列表加载失败：保留空态，下次打开归档视图重试
    } finally {
      setArchivedLoading(false);
    }
  }, []);

  useEffect(() => {
    if (showArchived) void loadArchived(0);
  }, [showArchived, loadArchived]);

  // 打开归档视图时先置 loading，避免第一帧闪现「暂无归档会话」。
  const toggleArchivedView = useCallback(() => {
    const next = !showArchived;
    setShowArchived(next);
    if (next) setArchivedLoading(true);
  }, [showArchived]);

  // 归档视图内删除：先本地移除，再走上层删除流程（失败时下次打开会重新出现）。
  const handleDeleteSession = useCallback(
    (sessionId: string) => {
      onDelete(sessionId);
      if (showArchived) {
        setArchivedSessions((prev) => (prev ? prev.filter((s) => s.id !== sessionId) : prev));
      }
    },
    [onDelete, showArchived],
  );
>>>>>>> origin/main

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
<<<<<<< HEAD
    const base = showArchived ? sessions : sessions.filter((s) => !s.is_archived);
=======
    // 默认视图：内存中的未归档会话；归档视图：按需拉取的归档会话。
    const base = showArchived ? (archivedSessions ?? []) : sessions.filter((s) => !s.is_archived);
>>>>>>> origin/main
    const q = trimmedQuery.toLowerCase();
    if (!q) return base;
    // 标题匹配优先;消息内容命中的会话（标题不匹配也）并入展示
    const titleMatches = base.filter((s) => s.title.toLowerCase().includes(q));
    const seen = new Set(titleMatches.map((s) => s.id));
    const messageMatches = base.filter((s) => !seen.has(s.id) && messageHits.has(s.id));
    return [...titleMatches, ...messageMatches];
<<<<<<< HEAD
  }, [sessions, trimmedQuery, messageHits, showArchived]);
=======
  }, [sessions, archivedSessions, trimmedQuery, messageHits, showArchived]);
>>>>>>> origin/main

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
<<<<<<< HEAD
        .then(() => onRefreshSessions?.())
=======
        .then((result) => {
          if (result.archived > 0) {
            toast.success(t('session.auto_archived').replace('{count}', String(result.archived)));
          }
          onRefreshSessions?.();
          if (showArchived) void loadArchived(0);
        })
>>>>>>> origin/main
        .catch(() => {
          /* sweep 失败静默，下次挂载重试 */
        });
    },
<<<<<<< HEAD
    [onRefreshSessions],
=======
    [onRefreshSessions, showArchived, loadArchived, t],
>>>>>>> origin/main
  );

  useEffect(() => {
    localStorage.setItem(AUTO_ARCHIVE_KEY, String(autoArchiveDays));
    sweep(autoArchiveDays);
  }, [autoArchiveDays, sweep]);

  const handlePurgeArchived = useCallback(async () => {
    // P1-8: 用项目内 confirmDialog 服务取代 window.confirm。
    const ok = await confirmDialog({
      title: '永久删除全部归档会话（含消息）？此操作不可撤销。',
      danger: true,
    });
    if (!ok) return;
    setPurging(true);
    void sessionApi
      .purgeArchived()
<<<<<<< HEAD
      .then(() => onRefreshSessions?.())
=======
      .then(() => {
        setArchivedSessions([]);
        onRefreshSessions?.();
      })
>>>>>>> origin/main
      .catch(() => {
        /* purge 失败静默，列表下次刷新恢复 */
      })
      .finally(() => setPurging(false));
  }, [onRefreshSessions]);

<<<<<<< HEAD
  const archivedCount = useMemo(
    () => sessions.filter((s) => s.is_archived).length,
    [sessions],
  );
=======
  // 手动归档 / 恢复：失败 toast 由上层（Sidebar）负责，这里只保证本地视图一致。
  const handleArchive = useCallback(
    async (sessionId: string) => {
      try {
        await onArchiveSession?.(sessionId);
      } catch {
        /* 失败时条目保留，用户可重试 */
      }
    },
    [onArchiveSession],
  );

  const handleUnarchive = useCallback(
    async (sessionId: string) => {
      try {
        await onUnarchiveSession?.(sessionId);
        setArchivedSessions((prev) => (prev ? prev.filter((s) => s.id !== sessionId) : prev));
      } catch {
        /* 失败时条目保留，用户可重试 */
      }
    },
    [onUnarchiveSession],
  );

  // 滚动触底加载：默认视图追加下一页；归档视图按需追加归档页。
  const handleListScroll = useCallback(
    (e: React.UIEvent<HTMLDivElement>) => {
      const el = e.currentTarget;
      if (el.scrollHeight - el.scrollTop - el.clientHeight > LOAD_MORE_THRESHOLD_PX) return;
      if (showArchived) {
        if (archivedHasMore && !archivedLoading) {
          void loadArchived(archivedSessions?.length ?? 0);
        }
      } else if (sessionsHasMore && !sessionsLoadingMore) {
        onLoadMoreSessions?.();
      }
    },
    [
      showArchived,
      archivedHasMore,
      archivedLoading,
      archivedSessions,
      loadArchived,
      sessionsHasMore,
      sessionsLoadingMore,
      onLoadMoreSessions,
    ],
  );

  const archivedCount = archivedSessions?.length ?? 0;
>>>>>>> origin/main
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  const auditInput: ConversationsSectionAuditInput = {
    totalCount: sessions.length,
    displayCount: displaySessions.length,
    archivedCount,
    showArchived,
    hasQuery: Boolean(trimmedQuery),
    virtualized: displaySessions.length > VIRTUALIZE_THRESHOLD,
  };
  const auditSnapshot = formatConversationsSectionAuditSnapshot(auditInput);
  const auditJson = formatConversationsSectionAuditJson(auditInput);
  /* v8 ignore start */
  const handleCopySnapshot = async () => {
    setCopiedSnapshot(true);
    try {
      await navigator.clipboard?.writeText(auditSnapshot);
    } catch {
      // ignore clipboard errors
    }
  };
  const handleCopyJson = async () => {
    setCopiedJson(true);
    try {
      await navigator.clipboard?.writeText(auditJson);
    } catch {
      // ignore clipboard errors
    }
  };
  /* v8 ignore stop */

  return (
    <SiderSection
      sectionKey="conversations"
      label={t('sider.section.conversations')}
      icon={MessageSquare}
      collapsed={collapsed}
      onToggleCollapsed={onToggleCollapsed}
      fill
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
        <div
          data-testid="conversations-section-body"
          data-conversations-section-audit={auditSnapshot}
<<<<<<< HEAD
          className="flex flex-col min-h-0"
=======
          className="flex flex-col min-h-0 flex-1"
>>>>>>> origin/main
        >
          <span className="sr-only">
            <span
              role="status"
              tabIndex={0}
              data-testid="conversations-section-audit-copy"
              data-conversations-section-audit={auditSnapshot}
              aria-label="复制会话分区审计快照"
              onClick={() => void handleCopySnapshot()}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  void handleCopySnapshot();
                }
              }}
            >
              {copiedSnapshot ? '已复制' : '快照'}
            </span>
            <span
              role="status"
              tabIndex={0}
              data-testid="conversations-section-audit-copy-json"
              data-conversations-section-audit-json={auditJson}
              aria-label="复制会话分区审计 JSON"
              onClick={() => void handleCopyJson()}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  void handleCopyJson();
                }
              }}
            >
              {copiedJson ? '已复制 JSON' : 'JSON'}
            </span>
          </span>
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
              className="w-full h-6 pl-6 pr-2 text-ui-sm rounded bg-bg-hover border border-transparent focus:border-primary focus:outline-none placeholder:text-muted"
            />
            <button
              type="button"
              data-testid="toggle-archived"
<<<<<<< HEAD
              onClick={() => setShowArchived((v) => !v)}
=======
              onClick={toggleArchivedView}
>>>>>>> origin/main
              className={`text-ui-2xs whitespace-nowrap ${showArchived ? 'text-primary' : 'text-muted hover:text-text'}`}
            >
              {showArchived ? '隐藏归档' : '归档'}
            </button>
          </div>
          {showArchived && (
            <div
              className="px-2 pb-1 flex items-center gap-2 text-ui-2xs text-muted"
              data-testid="archived-toolbar"
            >
              <label className="whitespace-nowrap flex items-center gap-1">
                自动归档
                <select
                  data-testid="auto-archive-select"
                  value={autoArchiveDays}
                  onChange={(e) => setAutoArchiveDays(Number(e.target.value))}
                  className="h-5 rounded bg-bg-hover border border-transparent focus:border-primary focus:outline-none text-ui-2xs"
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
<<<<<<< HEAD
          {sessions.length === 0 ? (
            <div className="px-3 py-6 text-ui-sm text-text-muted text-center space-y-2" data-testid="sessions-empty">
=======
          {!showArchived && sessions.length === 0 ? (
            <div
              className="px-3 py-6 text-ui-sm text-text-muted text-center space-y-2"
              data-testid="sessions-empty"
            >
>>>>>>> origin/main
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
            <div className="px-3 py-4 text-ui-sm text-text-muted text-center">
              {t('sidebar.no_match')}
            </div>
<<<<<<< HEAD
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
=======
          ) : displaySessions.length === 0 ? (
            <div className="px-3 py-4 text-ui-sm text-text-muted text-center">
              {showArchived ? (archivedLoading ? '加载中…' : '暂无归档会话') : '暂无对话记录'}
            </div>
          ) : (
            <div
              ref={listScrollRef}
              data-testid="session-list-scroll"
              className="flex-1 min-h-0 overflow-y-auto"
              onScroll={handleListScroll}
            >
              {displaySessions.length > VIRTUALIZE_THRESHOLD ? (
                <VirtualSessionList
                  sessions={displaySessions}
                  currentSessionId={currentSessionId}
                  onSelect={handleSelect}
                  onDelete={handleDeleteSession}
                  onRename={onRename}
                  messageHitsBySession={messageHits}
                  scrollElementRef={listScrollRef}
                  onArchive={showArchived ? undefined : (id) => void handleArchive(id)}
                  onUnarchive={showArchived ? (id) => void handleUnarchive(id) : undefined}
                />
              ) : (
                <SessionList
                  sessions={displaySessions}
                  currentSessionId={currentSessionId}
                  onSelect={handleSelect}
                  onDelete={handleDeleteSession}
                  onRename={onRename}
                  messageHitsBySession={messageHits}
                  onArchive={showArchived ? undefined : (id) => void handleArchive(id)}
                  onUnarchive={showArchived ? (id) => void handleUnarchive(id) : undefined}
                />
              )}
              {(showArchived ? archivedLoading : sessionsLoadingMore) && (
                <div
                  className="px-3 py-2 text-ui-2xs text-muted text-center"
                  data-testid="session-load-more"
                >
                  加载中…
                </div>
              )}
            </div>
>>>>>>> origin/main
          )}
        </div>
      )}
    />
  );
}
