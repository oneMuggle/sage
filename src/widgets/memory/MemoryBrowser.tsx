/**
 * MemoryBrowser - 记忆浏览器组件
 * 显示记忆列表，支持筛选、来源徽章和会话摘要视图。
 *
 * 批次三 step 6 (spec §4.3 line 150):
 * - 每条记忆按 ``source`` 字段渲染"working / 核心 / 摘要"徽章
 * - 携带 ``session_id`` 的记忆会显示来源会话,可点击跳转
 * - 提供"按会话查看摘要"模式,通过 ``memoryApi.getSessionSummaries`` 拉取
 *
 * P0-1 (2026-10-01):
 * - 接上此前零调用的 ``memoryApi.searchMemories`` / ``memoryApi.deleteMemory``。
 *   PHILOSOPHY.md 把"不可删除:用户无法清除记忆"列为反模式,而删除端点与
 *   两步确认组件早已存在却无渲染方 → 用户有一条错误记忆时无路可走。
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { memoryApi, Memory } from '../../shared/api';
import { agentsApi } from '../../shared/api/agentsApi';
import { QUALITY_LOW_THRESHOLD } from '../../shared/api/types/domainEntityTypes';

import { MemoryItemCard } from './MemoryItemCard';
import type { MemoryUpdatePayload } from './MemoryItemCard';

// Constants
const ONE_WEEK_MS = 7 * 24 * 60 * 60 * 1000;
const MEMORY_PAGE_SIZE = 100;
/** 搜索防抖 —— 与会话列表搜索(ConversationsSection)保持同一手速。 */
const SEARCH_DEBOUNCE_MS = 300;

type MemoryFilter = 'all' | 'episodic' | 'semantic' | 'working' | 'session_summary';
type ViewMode = 'all' | 'summaries';
// P1 (spec §4.3 scope 轴): 作用域筛选为纯前端过滤,不打扰后端分页契约。
type ScopeFilter = 'all' | 'user' | 'project' | 'global';
// M3-Task 6 (2026-11-04 专家归属轴): agent 维度走后端精确匹配,
// 'all' = 不过滤 / 'shared' = agent_id IS NULL / 其它 = 精确专家 id。
type AgentFilter = 'all' | 'shared' | string;

interface MemoryBrowserProps {
  initialType?: MemoryFilter;
  onNewMemory?: () => void;
  /**
   * Bump this value to force a reload from the API. Used by the parent
   * Memory page to refresh the list after a new memory is saved without
   * triggering a full page reload (fix/security-perf-quickwins §1.3b g).
   */
  refreshKey?: number;
  /**
   * P0-6: 来自聊天气泡记忆引用的深链定位 id。命中的那条会被高亮并滚动到
   * 可视区 —— 用户点「这条记忆凭什么影响我的答案」后需要立刻看到它。
   */
  focusMemoryId?: string;
  /**
   * M3-Task 6: 专家归属筛选变化回调 —— 父页面（Memory.tsx）导出时按当前
   * 筛选收窄范围。``null`` 表示'全部'（不过滤）。
   */
  onAgentFilterChange?: (agentId: string | null) => void;
}

const FILTER_LABELS: Record<MemoryFilter, string> = {
  all: '全部',
  episodic: '情景记忆',
  semantic: '语义记忆',
  working: '工作记忆',
  session_summary: '会话摘要',
};

const SCOPE_FILTER_LABELS: Record<ScopeFilter, string> = {
  all: '全部作用域',
  user: '用户',
  project: '项目',
  global: '全局',
};

export function MemoryBrowser({
  initialType = 'all',
  refreshKey,
  focusMemoryId,
  onAgentFilterChange,
}: MemoryBrowserProps) {
  const navigate = useNavigate();
  const [memories, setMemories] = useState<Memory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterType, setFilterType] = useState<MemoryFilter>(initialType);
  const [scopeFilter, setScopeFilter] = useState<ScopeFilter>('all');
  // M3-Task 6: 专家归属筛选(走后端 agent_id 精确过滤)。'all' = 管理口径不过滤。
  const [agentFilter, setAgentFilter] = useState<AgentFilter>('all');
  // 专家下拉候选 —— 组件挂载时拉一次;下拉只显示 id + display_name。
  const [agentOptions, setAgentOptions] = useState<{ id: string; name: string }[]>(() => [
    { id: 'shared', name: '共享层' },
  ]);
  const [viewMode, setViewMode] = useState<ViewMode>('all');
  const [summarySessionId, setSummarySessionId] = useState<string>('');
  // P0-1: 记忆检索。此前 ``memoryApi.searchMemories`` 已实现但全仓零调用。
  const [searchInput, setSearchInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [stats, setStats] = useState({
    total: 0,
    thisWeek: 0,
    episodic: 0,
    semantic: 0,
    working: 0,
    session_summary: 0,
    /** Task 4.4: quality_score < 0.4 的计数(仅 episodic/semantic 有语义)。 */
    lowQuality: 0,
  });

  // Task 4.3: 选择模式 + 批量清理低质量记忆。
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [qualityMode, setQualityMode] = useState(false);
  const [batchConfirming, setBatchConfirming] = useState(false);
  const [batchDeleting, setBatchDeleting] = useState(false);

  // 请求代际 + AbortController:
  // 快速切换 filter / viewMode 时旧响应可能晚到,把新响应覆盖。
  // 每次进入加载 ++gen,await 结束后若 genRef 已被新调用推进 → 静默放弃。
  // 同时 unmount 时 abort() 让 invoke 立刻结束,避免 setState on unmounted 警告。
  const requestGenRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  // M3-Task 6: 归属筛选变化时通知父页面（导出范围跟随当前筛选）。
  useEffect(() => {
    onAgentFilterChange?.(agentFilter === 'all' ? null : agentFilter);
  }, [agentFilter, onAgentFilterChange]);

  // P0-1: 输入防抖后再触发检索,避免每敲一个字打一次后端。
  useEffect(() => {
    const timer = setTimeout(() => setSearchQuery(searchInput.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // M3-Task 6: 拉取专家列表填充筛选下拉(共享层固定首项)。失败静默降级
  // 为只有"全部/共享层"两项,不阻塞主功能。
  useEffect(() => {
    let cancelled = false;
    agentsApi
      .list()
      .then((profiles) => {
        if (cancelled) return;
        const options = [{ id: 'shared', name: '共享层' }];
        for (const p of profiles || []) {
          if (!p?.id) continue;
          options.push({
            id: p.id,
            name: p.name || p.id,
          });
        }
        setAgentOptions(options);
      })
      .catch(() => {
        /* ignore */
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
      // P0-1: 检索态走 searchMemories(语义检索),空查询走原分页列表。
      // searchMemories 只接受 episodic/semantic —— working/session_summary
      // 归为 undefined 交由后端全量匹配,避免静默收窄结果集。
      if (searchQuery) {
        const searchType =
          filterType === 'episodic' || filterType === 'semantic' ? filterType : undefined;
        const hits = await memoryApi.searchMemories(searchQuery, searchType);
        if (gen !== requestGenRef.current) return;
        setMemories(hits);
        // 检索结果没有 source_breakdown,只更新"当前显示"总数,
        // 其余分类计数保持上一轮全量口径,避免展示成 0 误导。
        const lowQuality = hits.filter(
          (m) => typeof m.quality_score === 'number' && m.quality_score < QUALITY_LOW_THRESHOLD,
        ).length;
        setStats((prev) => ({ ...prev, total: hits.length, lowQuality }));
        return;
      }
      const response = await memoryApi.getMemories(type, 1, MEMORY_PAGE_SIZE, {
        signal: ac.signal,
        // M3-Task 6: 专家归属过滤。'all' = 不过滤（管理口径全量返回），
        // 其它值原样透传给后端 agent_id query（'shared' 映射 IS NULL）。
        agentId: agentFilter === 'all' ? null : agentFilter,
      });
      // 代际失配(用户已切到其他视图/筛选):丢弃本次响应
      if (gen !== requestGenRef.current) return;
      setMemories(response.items);
      // Task 4.4: 低质量计数 —— 只在 episodic/semantic 行上有 quality_score,
      // working/session_summary 行为 null, 不计入。
      const lowQuality = response.items.filter(
        (m) => typeof m.quality_score === 'number' && m.quality_score < QUALITY_LOW_THRESHOLD,
      ).length;
      // 用 envelope 的 source_breakdown 替换旧的 two-call fallback,更准。
      const breakdown = response.source_breakdown;
      setStats((prev) => ({
        ...prev,
        episodic: breakdown.episodic,
        semantic: breakdown.semantic,
        working: breakdown.working,
        session_summary: breakdown.session_summary,
        total: response.total,
        lowQuality,
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
  }, [filterType, searchQuery, agentFilter]);

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

  // Task 4.3: 低质量候选 —— 走 /memory/quality-candidates (最差优先)。
  // 映射为 Memory 形状,复用 MemoryItemCard 渲染;选择模式可直接批量删除。
  const loadQualityCandidates = useCallback(async () => {
    const gen = ++requestGenRef.current;
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;

    setLoading(true);
    setError(null);
    try {
      const candidates = await memoryApi.getQualityCandidates(50, QUALITY_LOW_THRESHOLD);
      if (gen !== requestGenRef.current) return;
      const mapped: Memory[] = candidates.map((c) => ({
        id: c.id,
        content: c.content,
        memory_type: c.memory_type,
        layer: c.memory_type,
        source: c.memory_type,
        importance: c.importance,
        tags: [],
        created_at: Math.floor((c.created_at_ms || 0) / 1000),
        created_at_ms: c.created_at_ms,
        access_count: c.access_count,
        quality_score: c.quality_score,
      }));
      setMemories(mapped);
      setSelectedIds(new Set());
      setStats((prev) => ({ ...prev, total: mapped.length, lowQuality: mapped.length }));
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
  }, []);

  useEffect(() => {
    if (viewMode !== 'all') return;
    if (qualityMode) {
      void loadQualityCandidates();
    } else {
      void loadMemories();
    }
  }, [viewMode, qualityMode, loadQualityCandidates, loadMemories]);

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
    if (refreshKey === undefined || viewMode !== 'all' || qualityMode) return;
    void loadMemories();
  }, [refreshKey, viewMode, qualityMode, loadMemories]);

  const handleJumpToSession = useCallback(
    (sessionId: string | undefined) => {
      if (!sessionId) return;
      // spec §4.3 line 150 要求"保留来源 session 跳转",跳到聊天页并锁定会话。
      navigate(`/chat?session=${encodeURIComponent(sessionId)}`);
    },
    [navigate],
  );

  // P0-1: 删除记忆 —— 接上此前零调用的 ``memoryApi.deleteMemory``。
  // 失败时保留该行并明确告知,不做"看起来删掉了"的静默移除
  // (PHILOSOPHY「静默失败」反模式)。
  //
  // 注意:失败**不走** setError —— 那是列表级错误态,一设置就会把整个
  // 记忆库替换成「加载失败 + 重试」,而列表本身并无问题。此处只报 toast。
  const handleDeleteMemory = useCallback(async (memory: Memory) => {
    try {
      await memoryApi.deleteMemory(memory.id);
      setMemories((prev) => prev.filter((m) => m.id !== memory.id));
      setStats((prev) => ({ ...prev, total: Math.max(0, prev.total - 1) }));
      toast.success('记忆已删除', {
        description: (memory.content || memory.summary || '').split('\n')[0].slice(0, 40),
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : '删除失败';
      toast.error('删除失败', { description: `${message}（该条记忆仍保留）` });
    }
  }, []);

  // M3-Task 7: 把一条私有记忆提升到共享层。归属从专家私有改为共享
  // (agent_id → NULL),所有专家此后都能读到。失败时保留该行并明确告知,
  // 与删除路径同一原则 —— 不做"看起来公开了"的静默状态翻转。
  const handlePromoteMemory = useCallback(async (memory: Memory) => {
    try {
      const result = await memoryApi.promoteMemory(memory.id);
      setMemories((prev) =>
        prev.map((m) => (m.id === memory.id ? { ...m, agent_id: undefined } : m)),
      );
      toast.success(result.status === 'already_shared' ? '该记忆已在共享层' : '记忆已提升为共享', {
        description: (memory.content || memory.summary || '').split('\n')[0].slice(0, 40),
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : '提升失败';
      toast.error('提升为共享失败', { description: `${message}（该条记忆归属未变）` });
    }
  }, []);
  // 2026-11-17: 编辑记忆（内容/标题）—— 成功后用后端返回的记录替换列表项,
  // 不做整页刷新;失败向上抛由卡片 toast 兜底（不静默改行）。
  const handleUpdateMemory = useCallback(async (memory: Memory, patch: MemoryUpdatePayload) => {
    const updated = await memoryApi.updateMemory(memory.id, patch);
    setMemories((prev) => prev.map((m) => (m.id === memory.id ? { ...m, ...updated } : m)));
  }, []);
  // Task 4.3: 选择模式 —— 只有 episodic / semantic / working 可批量删除,
  // session_summary 不在 MemoryManager.delete_memory 的路由内。
  const toggleSelect = useCallback((memory: Memory) => {
    if (!resolveSelectableType(memory)) return;
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(memory.id)) {
        next.delete(memory.id);
      } else {
        next.add(memory.id);
      }
      return next;
    });
  }, []);

  const exitSelectMode = useCallback(() => {
    setSelectMode(false);
    setSelectedIds(new Set());
    setBatchConfirming(false);
  }, []);

  // Task 4.3: 批量删除 —— 两步确认后逐条交给后端 batch-delete。
  // 失败条目保留在列表里并汇总告知(不静默移除)。
  const handleBatchDelete = useCallback(async () => {
    const selected = memories.filter((m) => selectedIds.has(m.id));
    const items: Array<{ id: string; memory_type: 'episodic' | 'semantic' | 'working' }> = [];
    for (const m of selected) {
      const t = resolveSelectableType(m);
      if (t) items.push({ id: m.id, memory_type: t });
    }
    if (items.length === 0) {
      setBatchConfirming(false);
      return;
    }

    setBatchDeleting(true);
    try {
      const res = await memoryApi.batchDeleteMemories(items);
      const failedIds = new Set(res.failed.map((f) => f.id));
      const deletedIds = new Set(items.map((i) => i.id).filter((id) => !failedIds.has(id)));
      setMemories((prev) => prev.filter((m) => !deletedIds.has(m.id)));
      setSelectedIds(new Set());
      setBatchConfirming(false);
      setStats((prev) => ({ ...prev, total: Math.max(0, prev.total - res.deleted) }));
      if (res.failed.length > 0) {
        toast.warning(`已删除 ${res.deleted} 条，${res.failed.length} 条失败`, {
          description: res.failed
            .slice(0, 3)
            .map((f) => `${truncate(f.id, 12)}: ${f.reason}`)
            .join('；'),
        });
      } else {
        toast.success(`已删除 ${res.deleted} 条记忆`);
      }
      // 候选模式下重新拉取,补足被删条目空出的名额并保持排序一致。
      if (qualityMode) void loadQualityCandidates();
    } catch (err) {
      const message = err instanceof Error ? err.message : '批量删除失败';
      toast.error('批量删除失败', { description: `${message}（未删除任何记忆）` });
    } finally {
      setBatchDeleting(false);
    }
  }, [memories, selectedIds, qualityMode, loadQualityCandidates]);

  // 作用域为纯前端过滤(后端 list 契约不变)。缺 scope 的旧行按 DB 默认
  // 'user' 处理,与后端 visibility 规则一致。
  const visibleMemories = useMemo(() => {
    if (scopeFilter === 'all') return memories;
    return memories.filter((m) => (m.scope ?? 'user') === scopeFilter);
  }, [memories, scopeFilter]);

  return (
    <div>
      {/* 统计卡片 — step 6 起展示 4 个 source 计数。Task 4.4 起加"低质量"。 */}
      <div className="flex gap-3 mb-5">
        <StatCard value={stats.total} label="当前显示" />
        <StatCard value={stats.thisWeek} label="本周新增" />
        <StatCard value={stats.episodic} label="情景" />
        <StatCard value={stats.semantic} label="语义" />
        <StatCard value={stats.working} label="工作" />
        <StatCard value={stats.session_summary} label="摘要" />
        <StatCard
          value={stats.lowQuality}
          label="低质量"
          variant={stats.lowQuality > 0 ? 'error' : 'neutral'}
        />
      </div>

      {/* 视图模式切换 */}
      <div className="flex items-center gap-2 mb-4">
        {viewMode === 'all' && (
          <div className="relative flex-1 max-w-xs">
            <input
              type="search"
              data-testid="memory-search-input"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="搜索记忆内容…"
              aria-label="搜索记忆"
              className="w-full px-2 py-1 border border-border rounded-radius-sm text-xs bg-surface text-text placeholder:text-muted"
            />
          </div>
        )}
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
        {viewMode === 'all' && (
          <button
            data-testid="memory-select-mode-toggle"
            className={`px-3 py-1 border border-border rounded-radius-sm text-xs cursor-pointer font-mono ${
              selectMode
                ? 'bg-primary/10 text-primary border-primary'
                : 'bg-surface text-muted hover:text-text'
            }`}
            onClick={() => {
              if (selectMode) {
                exitSelectMode();
              } else {
                setSelectMode(true);
                setSelectedIds(new Set());
                setBatchConfirming(false);
              }
            }}
          >
            {selectMode ? '退出选择' : '选择'}
          </button>
        )}
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
        <div className="flex gap-1.5 mb-2 flex-wrap">
          {Object.entries(FILTER_LABELS).map(([key, label]) => (
            <button
              key={key}
              className={`px-3 py-1 border border-border rounded-radius-sm text-xs cursor-pointer font-mono ${
                !qualityMode && filterType === key
                  ? 'bg-primary/10 text-primary border-primary'
                  : 'bg-surface text-muted hover:text-text'
              }`}
              onClick={() => {
                setFilterType(key as MemoryFilter);
                setQualityMode(false);
                setBatchConfirming(false);
              }}
            >
              {label}
            </button>
          ))}
          {/* Task 4.3: 低质量候选 —— 只看质量分 < 0.4 的记忆,最差优先 */}
          <button
            data-testid="memory-quality-candidates-toggle"
            className={`px-3 py-1 border border-border rounded-radius-sm text-xs cursor-pointer font-mono ${
              qualityMode
                ? 'bg-error/10 text-error border-error'
                : 'bg-surface text-muted hover:text-text'
            }`}
            onClick={() => {
              setQualityMode((v) => !v);
              setBatchConfirming(false);
            }}
            title="只看质量分低于 0.4 的记忆（按最差优先）"
          >
            低质量候选
          </button>
        </div>
      )}

      {/* P1 scope 轴:作用域筛选(前端过滤) */}
      {viewMode === 'all' && (
        <div className="flex items-center gap-1.5 mb-4 flex-wrap">
          <span className="text-ui-2xs text-muted font-mono mr-1">作用域</span>
          {Object.entries(SCOPE_FILTER_LABELS).map(([key, label]) => (
            <button
              key={key}
              className={`px-3 py-1 border border-border rounded-radius-sm text-xs cursor-pointer font-mono ${
                scopeFilter === key
                  ? 'bg-primary/10 text-primary border-primary'
                  : 'bg-surface text-muted hover:text-text'
              }`}
              onClick={() => setScopeFilter(key as ScopeFilter)}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {/* M3-Task 6: 专家归属筛选(后端精确过滤)。'all' 显示全部管理口径。 */}
      {viewMode === 'all' && (
        <div className="flex items-center gap-1.5 mb-4 flex-wrap">
          <span className="text-ui-2xs text-muted font-mono mr-1">归属</span>
          {agentOptions.map((opt) => (
            <button
              key={opt.id}
              className={`px-3 py-1 border border-border rounded-radius-sm text-xs cursor-pointer font-mono ${
                agentFilter === opt.id
                  ? 'bg-primary/10 text-primary border-primary'
                  : 'bg-surface text-muted hover:text-text'
              }`}
              onClick={() => setAgentFilter(opt.id)}
              title={opt.id === 'shared' ? '共享层（所有专家可见）' : `专家 ${opt.name}`}
            >
              {opt.name}
            </button>
          ))}
        </div>
      )}
      {/* Task 4.3: 低质量候选说明条 */}
      {viewMode === 'all' && qualityMode && !loading && !error && (
        <div className="mb-3 px-3 py-2 border border-error/30 bg-error/5 rounded-radius-sm text-xs text-error">
          低质量候选 · {memories.length} 条（质量分 &lt; 0.4，按最差优先）
          {!selectMode && ' — 点「选择」后可批量清理'}
        </div>
      )}

      {/* Task 4.3: 选择模式计数栏 + 两步确认批量删除 */}
      {viewMode === 'all' && selectMode && (
        <div className="flex items-center gap-3 mb-3 px-3 py-2 border border-primary/20 bg-primary/5 rounded-radius-sm flex-wrap">
          <span className="text-xs font-mono text-text">已选 {selectedIds.size} 条</span>
          {batchConfirming ? (
            <>
              <span className="text-xs text-error">
                即将删除 {selectedIds.size} 条记忆（不可撤销）
              </span>
              <button
                type="button"
                data-testid="memory-batch-confirm"
                disabled={batchDeleting}
                onClick={() => void handleBatchDelete()}
                className="px-3 py-1 border border-error rounded-radius-sm text-xs text-error hover:bg-error/10 disabled:opacity-50"
              >
                {batchDeleting ? '删除中…' : '确认批量删除'}
              </button>
              <button
                type="button"
                data-testid="memory-batch-cancel"
                disabled={batchDeleting}
                onClick={() => setBatchConfirming(false)}
                className="px-3 py-1 border border-border rounded-radius-sm text-xs text-muted hover:text-text disabled:opacity-50"
              >
                取消
              </button>
            </>
          ) : (
            <button
              type="button"
              data-testid="memory-batch-delete"
              disabled={selectedIds.size === 0}
              onClick={() => setBatchConfirming(true)}
              className="px-3 py-1 border border-error rounded-radius-sm text-xs text-error hover:bg-error/10 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              批量删除
            </button>
          )}
          <button
            type="button"
            onClick={exitSelectMode}
            className="ml-auto px-3 py-1 border border-border rounded-radius-sm text-xs text-muted hover:text-text"
          >
            退出选择
          </button>
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
      ) : visibleMemories.length === 0 ? (
        <div className="text-center text-muted py-12 text-sm">
          {memories.length > 0 && (scopeFilter !== 'all' || agentFilter !== 'all')
            ? '当前筛选下暂无记忆'
            : '暂无记忆'}
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {visibleMemories.map((memory) => (
            <MemoryItemCard
              key={memory.id}
              memory={memory}
              onJumpToSession={handleJumpToSession}
              onDelete={handleDeleteMemory}
              onPromote={handlePromoteMemory}
              onUpdate={handleUpdateMemory}
              focused={memory.id === focusMemoryId}
              selectable={selectMode && resolveSelectableType(memory) !== null}
              selected={selectedIds.has(memory.id)}
              onToggleSelect={toggleSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function StatCard({
  value,
  label,
  variant = 'neutral',
}: {
  value: number;
  label: string;
  /** Task 4.4 起:error 变体用于低质量等告警类指标。 */
  variant?: 'neutral' | 'error';
}) {
  const bg = variant === 'error' ? 'bg-error/10 border-error/30' : 'bg-surface border-border';
  const fg = variant === 'error' ? 'text-error' : 'text-text';
  return (
    <div className={`flex-1 p-3.5 border border-border rounded-radius-sm ${bg}`}>
      <div className={`text-xl font-bold font-mono ${fg}`}>{value}</div>
      <div className="text-xs text-muted mt-1">{label}</div>
    </div>
  );
}

/** Task 4.3: 批量删除只支持 MemoryManager.delete_memory 有路由的三类。 */
function resolveSelectableType(memory: Memory): 'episodic' | 'semantic' | 'working' | null {
  const t = memory.memory_type;
  if (t === 'episodic' || t === 'semantic' || t === 'working') return t;
  const s = memory.source ?? memory.layer;
  if (s === 'episodic' || s === 'semantic' || s === 'working') return s;
  return null;
}

// formatDate 已统一到 src/shared/lib/timeFormatter

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return `${s.slice(0, max - 1)}…`;
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditMemoryBrowserGovernance(): string {
  return JSON.stringify({
    module: 'memory-browser',
    phase: 'P191',
    audited: true,
  });
}
