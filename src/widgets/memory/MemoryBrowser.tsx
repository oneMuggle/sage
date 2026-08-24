/**
 * MemoryBrowser - 记忆浏览器组件
 * 显示记忆列表，支持筛选、来源徽章和会话摘要视图。
 *
 * 批次三 step 6 (spec §4.3 line 150):
 * - 每条记忆按 ``source`` 字段渲染"working / 核心 / 摘要"徽章
 * - 携带 ``session_id`` 的记忆会显示来源会话,可点击跳转
 * - 提供"按会话查看摘要"模式,通过 ``memoryApi.getSessionSummaries`` 拉取
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

import { memoryApi, Memory } from '../../shared/api';

// Constants
const ONE_WEEK_MS = 7 * 24 * 60 * 60 * 1000;
const MEMORY_PAGE_SIZE = 100;

type MemoryFilter = 'all' | 'episodic' | 'semantic' | 'working' | 'session_summary';
type ViewMode = 'all' | 'summaries';

interface MemoryBrowserProps {
  initialType?: MemoryFilter;
  onNewMemory?: () => void;
  /**
   * Bump this value to force a reload from the API. Used by the parent
   * Memory page to refresh the list after a new memory is saved without
   * triggering a full page reload (fix/security-perf-quickwins §1.3b g).
   */
  refreshKey?: number;
}

const FILTER_LABELS: Record<MemoryFilter, string> = {
  all: '全部',
  episodic: '情景记忆',
  semantic: '语义记忆',
  working: '工作记忆',
  session_summary: '会话摘要',
};

// 来源徽章样式 — 与浅色卡片对比度足够,聚焦层信息不抢主标题。
const SOURCE_BADGE_CLASSES: Record<string, string> = {
  episodic: 'bg-primary/10 text-primary',
  semantic: 'bg-warning/10 text-warning',
  working: 'bg-success/10 text-success',
  session_summary: 'bg-info/10 text-info',
};

const SOURCE_LABEL: Record<string, string> = {
  episodic: '情景',
  semantic: '语义',
  working: '工作',
  session_summary: '摘要',
};

const SUMMARY_STATUS_LABEL: Record<string, string> = {
  ready: '已就绪',
  pending: '生成中',
  failed: '失败',
};

export function MemoryBrowser({ initialType = 'all', refreshKey }: MemoryBrowserProps) {
  const navigate = useNavigate();
  const [memories, setMemories] = useState<Memory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterType, setFilterType] = useState<MemoryFilter>(initialType);
  const [viewMode, setViewMode] = useState<ViewMode>('all');
  const [summarySessionId, setSummarySessionId] = useState<string>('');
  const [stats, setStats] = useState({
    total: 0,
    thisWeek: 0,
    episodic: 0,
    semantic: 0,
    working: 0,
    session_summary: 0,
  });

  // 请求代际 + AbortController:
  // 快速切换 filter / viewMode 时旧响应可能晚到,把新响应覆盖。
  // 每次进入加载 ++gen,await 结束后若 genRef 已被新调用推进 → 静默放弃。
  // 同时 unmount 时 abort() 让 invoke 立刻结束,避免 setState on unmounted 警告。
  const requestGenRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      // 组件卸载 → 中止正在飞的请求,不再 setState
      abortRef.current?.abort();
    };
  }, []);

  // 加载记忆
  const loadMemories = useCallback(async () => {
    const gen = ++requestGenRef.current;
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;

    setLoading(true);
    setError(null);
    try {
      const type = filterType === 'all' ? undefined : filterType;
      const response = await memoryApi.getMemories(type, 1, MEMORY_PAGE_SIZE, {
        signal: ac.signal,
      });
      // 代际失配(用户已切到其他视图/筛选):丢弃本次响应
      if (gen !== requestGenRef.current) return;
      setMemories(response.items);
      // 用 envelope 的 source_breakdown 替换旧的 two-call fallback,更准。
      const breakdown = response.source_breakdown;
      setStats((prev) => ({
        ...prev,
        episodic: breakdown.episodic,
        semantic: breakdown.semantic,
        working: breakdown.working,
        session_summary: breakdown.session_summary,
        total: response.total,
      }));
    } catch (err) {
      if (ac.signal.aborted || gen !== requestGenRef.current) return;
      const message = err instanceof Error ? err.message : '加载失败';
      setError(message);
      setMemories([]);
    } finally {
      if (gen === requestGenRef.current) {
        setLoading(false);
      }
    }
  }, [filterType]);

  // 加载摘要视图(批次三 step 6 新增) — 需要指定 session_id。
  const loadSummaries = useCallback(
    async (sessionId = summarySessionId) => {
      const trimmed = sessionId.trim();
      if (!trimmed) {
        setError('请输入会话 ID 以查看摘要');
        setMemories([]);
        setLoading(false);
        return;
      }
      const gen = ++requestGenRef.current;
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;

      setLoading(true);
      setError(null);
      try {
        const response = await memoryApi.getSessionSummaries(trimmed, 1, MEMORY_PAGE_SIZE, {
          signal: ac.signal,
        });
        if (gen !== requestGenRef.current) return;
        setMemories(response.items);
        setStats((prev) => ({
          ...prev,
          session_summary: response.total,
          total: response.total,
        }));
      } catch (err) {
        if (ac.signal.aborted || gen !== requestGenRef.current) return;
        const message = err instanceof Error ? err.message : '加载失败';
        setError(message);
        setMemories([]);
      } finally {
        if (gen === requestGenRef.current) {
          setLoading(false);
        }
      }
    },
    [summarySessionId],
  );

  useEffect(() => {
    if (viewMode === 'all') {
      void loadMemories();
    }
  }, [viewMode, loadMemories]);

  useEffect(() => {
    if (viewMode !== 'all') return;
    setStats((prev) => {
      const thisWeek = memories.filter((m) => {
        const ts = m.created_at_ms ?? m.created_at * 1000;
        return Date.now() - ts < ONE_WEEK_MS;
      }).length;
      return { ...prev, thisWeek };
    });
  }, [memories, viewMode]);

  // Parent (Memory.tsx) bumps refreshKey after a successful save to
  // re-fetch the list without a full page reload.
  useEffect(() => {
    if (refreshKey === undefined || viewMode !== 'all') return;
    void loadMemories();
  }, [refreshKey, viewMode, loadMemories]);

  const handleJumpToSession = useCallback(
    (sessionId: string | undefined) => {
      if (!sessionId) return;
      // spec §4.3 line 150 要求"保留来源 session 跳转",跳到聊天页并锁定会话。
      navigate(`/chat?session=${encodeURIComponent(sessionId)}`);
    },
    [navigate],
  );

  return (
    <div>
      {/* 统计卡片 — step 6 起展示 4 个 source 计数。 */}
      <div className="flex gap-3 mb-5">
        <StatCard value={stats.total} label="当前显示" />
        <StatCard value={stats.thisWeek} label="本周新增" />
        <StatCard value={stats.episodic} label="情景" />
        <StatCard value={stats.semantic} label="语义" />
        <StatCard value={stats.working} label="工作" />
        <StatCard value={stats.session_summary} label="摘要" />
      </div>

      {/* 视图模式切换 */}
      <div className="flex items-center gap-2 mb-4">
        <button
          className={`px-3 py-1 border border-border rounded-radius-sm text-xs cursor-pointer font-mono ${
            viewMode === 'all'
              ? 'bg-primary/10 text-primary border-primary'
              : 'bg-surface text-muted hover:text-text'
          }`}
          onClick={() => setViewMode('all')}
        >
          全部记忆
        </button>
        <button
          className={`px-3 py-1 border border-border rounded-radius-sm text-xs cursor-pointer font-mono ${
            viewMode === 'summaries'
              ? 'bg-primary/10 text-primary border-primary'
              : 'bg-surface text-muted hover:text-text'
          }`}
          onClick={() => setViewMode('summaries')}
        >
          按会话查看摘要
        </button>
        {viewMode === 'summaries' && (
          <div className="flex items-center gap-2 ml-2">
            <input
              type="text"
              value={summarySessionId}
              onChange={(e) => setSummarySessionId(e.target.value)}
              placeholder="session_id"
              className="px-2 py-1 border border-border rounded text-xs font-mono bg-surface text-text w-48"
            />
            <button
              onClick={() => void loadSummaries()}
              className="px-3 py-1 border border-border rounded-radius-sm text-xs bg-primary text-text-inverse hover:bg-primary-hover transition-colors"
            >
              刷新
            </button>
          </div>
        )}
      </div>

      {/* 筛选按钮 — step 6 起扩展到 working / session_summary */}
      {viewMode === 'all' && (
        <div className="flex gap-1.5 mb-4 flex-wrap">
          {Object.entries(FILTER_LABELS).map(([key, label]) => (
            <button
              key={key}
              className={`px-3 py-1 border border-border rounded-radius-sm text-xs cursor-pointer font-mono ${
                filterType === key
                  ? 'bg-primary/10 text-primary border-primary'
                  : 'bg-surface text-muted hover:text-text'
              }`}
              onClick={() => setFilterType(key as MemoryFilter)}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {/* 记忆列表 */}
      {loading ? (
        <div className="text-center text-muted py-12 text-sm">加载中...</div>
      ) : error ? (
        <div className="text-center py-12">
          <div className="text-sm text-error mb-2">{error}</div>
          <button
            onClick={viewMode === 'all' ? loadMemories : () => void loadSummaries()}
            className="px-3 py-1.5 text-xs border border-error rounded-radius-sm text-error hover:bg-error/5 transition-colors"
          >
            重试
          </button>
        </div>
      ) : memories.length === 0 ? (
        <div className="text-center text-muted py-12 text-sm">暂无记忆</div>
      ) : (
        <div className="flex flex-col gap-2">
          {memories.map((memory) => (
            <MemoryItemCard key={memory.id} memory={memory} onJumpToSession={handleJumpToSession} />
          ))}
        </div>
      )}
    </div>
  );
}

function StatCard({ value, label }: { value: number; label: string }) {
  return (
    <div className="flex-1 p-3.5 border border-border rounded-radius-sm bg-surface">
      <div className="text-xl font-bold font-mono text-text">{value}</div>
      <div className="text-xs text-muted mt-1">{label}</div>
    </div>
  );
}

function MemoryItemCard({
  memory,
  onJumpToSession,
}: {
  memory: Memory;
  onJumpToSession: (sessionId: string | undefined) => void;
}) {
  const source = memory.source || memory.layer || memory.memory_type || 'episodic';
  const sourceLabel = SOURCE_LABEL[source] || source;
  const sourceClass = SOURCE_BADGE_CLASSES[source] || SOURCE_BADGE_CLASSES.episodic;

  const content = memory.content || memory.summary || '无内容';
  const title = (content.split('\n')[0] || '无标题').substring(0, 30);
  const status = memory.status;
  const statusLabel = status ? SUMMARY_STATUS_LABEL[status] || status : null;

  // 来源 session 跳转 — spec §4.3 line 150 要求"保留来源 session 跳转"。
  // 只对携带 session_id 的行(episodic/semantic/session_summary)显示。
  // null/空串/非 string 一律视为未携带,不渲染跳转按钮。
  const rawSessionId = memory.session_id;
  const sessionId =
    typeof rawSessionId === 'string' && rawSessionId.trim() ? rawSessionId.trim() : undefined;
  const showSessionLink = Boolean(sessionId);

  // 时间戳兜底:毫秒缺失但秒在 → 转毫秒;两者皆无 → 0(由 formatDate 兜底为 '—')。
  const timestampMs =
    typeof memory.created_at_ms === 'number' && Number.isFinite(memory.created_at_ms)
      ? memory.created_at_ms
      : typeof memory.created_at === 'number' && Number.isFinite(memory.created_at)
        ? memory.created_at * 1000
        : 0;
  const importance =
    typeof memory.importance === 'number' && Number.isFinite(memory.importance)
      ? memory.importance
      : 0;
  const accessCount =
    typeof memory.access_count === 'number' && Number.isFinite(memory.access_count)
      ? memory.access_count
      : 0;

  return (
    <div className="p-3 border border-border rounded-radius-sm bg-surface cursor-pointer hover:border-primary transition-colors">
      <div className="flex items-center justify-between mb-1 gap-2">
        <span className="font-semibold text-sm text-text truncate flex-1">{title}</span>
        <div className="flex items-center gap-1.5">
          <span
            className={`text-[11px] px-2 py-0.5 rounded font-mono ${sourceClass}`}
            title={`来源: ${source}`}
          >
            {sourceLabel}
          </span>
          {statusLabel && (
            <span
              className={`text-[11px] px-2 py-0.5 rounded font-mono ${
                status === 'failed'
                  ? 'bg-error/10 text-error'
                  : status === 'pending'
                    ? 'bg-muted/20 text-muted'
                    : 'bg-success/10 text-success'
              }`}
              title={memory.error_message || statusLabel}
            >
              {statusLabel}
            </span>
          )}
        </div>
      </div>
      <div className="text-xs text-muted leading-relaxed">
        {content.length > 80 ? content.substring(0, 80) + '...' : content}
      </div>
      <div className="text-[11px] text-muted mt-1.5 font-mono flex items-center gap-2 flex-wrap">
        <span>
          创建于 {formatDate(timestampMs)} · 引用 {accessCount} 次 · 置信度{' '}
          {(importance / 10).toFixed(2)}
        </span>
        {showSessionLink && sessionId && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onJumpToSession(sessionId);
            }}
            className="text-primary hover:underline"
            title={`跳转到会话 ${sessionId}`}
          >
            ↳ 会话 {truncate(sessionId, 12)}
          </button>
        )}
      </div>
    </div>
  );
}

function formatDate(timestampMs: number): string {
  if (!Number.isFinite(timestampMs) || timestampMs <= 0) return '—';
  const date = new Date(timestampMs);
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return `${s.slice(0, max - 1)}…`;
}
