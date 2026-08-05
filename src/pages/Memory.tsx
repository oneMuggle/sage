/**
 * Memory - 记忆管理页（Gap E / Task 5）。
 *
 * 3 个 Tab：
 * - 所有记忆：window.electronAPI.memory.list({ page, page_size, type })，
 *   有搜索词时走 memory.search({ query, type })。
 * - 用户档案：memory.getProfile() → preferences + decisions + facts。
 * - 会话摘要：invoke('list_sessions') 列出会话，选中后调
 *   memory.getSummary({ session_id }) 展示 task_summary 记忆。
 *
 * 渲染层复用 MemoryCard（含点击跳回产生该记忆的会话/轮次）。
 */
import { Search } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { useStore } from '../shared/lib/store';
import { MemoryCard, type MemoryItem } from '../widgets/memory/MemoryCard';
import { MemoryTabs, type MemoryTab } from '../widgets/memory/MemoryTabs';

interface SessionInfo {
  id: string;
  title: string;
}

/** 归一化后端响应（数组 / { items } / { memories } / { summaries }）。 */
function toItems(data: unknown): MemoryItem[] {
  if (Array.isArray(data)) return data as MemoryItem[];
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>;
    for (const key of ['items', 'memories', 'summaries']) {
      if (Array.isArray(obj[key])) return obj[key] as MemoryItem[];
    }
  }
  return [];
}

const TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: '全部类型' },
  { value: 'user_pref', label: '用户偏好' },
  { value: 'project_fact', label: '项目事实' },
  { value: 'task_summary', label: '任务总结' },
  { value: 'decision', label: '决策' },
  { value: 'cross_session_pattern', label: '跨会话模式' },
];

export function Memory() {
  const [tab, setTab] = useState<MemoryTab>('all');
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [summaries, setSummaries] = useState<MemoryItem[]>([]);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [selectedSession, setSelectedSession] = useState('');
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const currentSessionId = useStore((s) => s.currentSessionId);

  // 卸载守卫：异步响应回来时组件已卸载则跳过 setState。
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // 最新值 refs —— SSE 轮询回退需要读到"当前"的 tab / search / typeFilter，
  // 而不用把 interval 依赖进 effect 导致反复重建。
  const tabRef = useRef(tab);
  useEffect(() => {
    tabRef.current = tab;
  }, [tab]);
  const searchRef = useRef(search);
  useEffect(() => {
    searchRef.current = search;
  }, [search]);
  const typeFilterRef = useRef(typeFilter);
  useEffect(() => {
    typeFilterRef.current = typeFilter;
  }, [typeFilter]);

  /** 重新加载"所有记忆" Tab 列表（SSE 轮询回退用；其它 Tab 不覆盖）。 */
  const reloadAll = useCallback(() => {
    if (tabRef.current !== 'all') return;
    const api = window.electronAPI;
    if (!api?.memory) return;
    const q = searchRef.current.trim();
    const promise = q
      ? api.memory.search({ query: q, type: typeFilterRef.current || undefined })
      : api.memory.list({ page: 1, page_size: 50, type: typeFilterRef.current || undefined });
    promise
      .then((data) => {
        if (mountedRef.current) setMemories(toItems(data));
      })
      .catch(() => {
        if (mountedRef.current) setMemories([]);
      });
  }, []);

  // Task 6 — 实时新记忆：订阅 SSE memory_written 事件（经 Electron relay
  // 转发）。事件到达 → toast「🧠 已记住: ...」+ 把新记忆 prepend 到列表头部。
  // subscribe 不存在或抛错（SSE 不可用）→ 回退到 30s setInterval 轮询 reloadAll。
  useEffect(() => {
    const api = window.electronAPI;
    let unsub: (() => void) | null = null;
    let pollId: number | null = null;

    if (api?.memory?.subscribe) {
      try {
        unsub = api.memory.subscribe((event: unknown) => {
          let data: Record<string, unknown>;
          try {
            data =
              typeof event === 'string'
                ? (JSON.parse(event) as Record<string, unknown>)
                : ((event ?? {}) as Record<string, unknown>);
          } catch {
            return; // 非 JSON 事件直接忽略
          }
          const content = typeof data.content === 'string' ? data.content : '';
          if (!content) return;
          toast.success(`🧠 已记住: ${content}`);
          setMemories((prev) => [
            {
              id: typeof data.memory_id === 'string' ? data.memory_id : `sse-${Date.now()}`,
              content,
              importance: typeof data.importance === 'number' ? data.importance : 5,
              memory_category:
                typeof data.memory_category === 'string' ? data.memory_category : undefined,
              session_id: typeof data.session_id === 'string' ? data.session_id : undefined,
              source_turn_id: typeof data.turn_id === 'string' ? data.turn_id : undefined,
              created_at: typeof data.timestamp === 'string' ? data.timestamp : Date.now(),
            },
            ...prev,
          ]);
        });
      } catch (e) {
        console.warn('[Memory] SSE subscribe failed, falling back to polling', e);
        unsub = null;
      }
    }

    if (!unsub) {
      pollId = window.setInterval(reloadAll, 30_000);
    }

    return () => {
      unsub?.();
      if (pollId !== null) window.clearInterval(pollId);
    };
  }, [reloadAll]);

  useEffect(() => {
    let cancelled = false;
    const api = window.electronAPI;
    if (!api?.memory) {
      setMemories([]);
      setSummaries([]);
      return;
    }

    if (tab === 'profile') {
      api.memory
        .getProfile()
        .then((data) => {
          const profile = (data ?? {}) as {
            preferences?: unknown;
            decisions?: unknown;
            facts?: unknown;
          };
          if (!cancelled) {
            setMemories([
              ...toItems(profile.preferences),
              ...toItems(profile.decisions),
              ...toItems(profile.facts),
            ]);
          }
        })
        .catch(() => {
          if (!cancelled) setMemories([]);
        });
      return;
    }

    if (tab === 'summary') {
      api
        .invoke('list_sessions', { limit: 50, offset: 0 })
        .then((raw) => {
          const list = Array.isArray(raw) ? (raw as SessionInfo[]) : [];
          if (cancelled) return;
          setSessions(list);
          const target = currentSessionId || list[0]?.id || '';
          setSelectedSession(target);
          if (!target) {
            setSummaries([]);
            return;
          }
          return api.memory.getSummary({ session_id: target });
        })
        .then((data) => {
          if (!cancelled) {
            setSummaries(toItems((data as { summaries?: unknown } | undefined)?.summaries));
          }
        })
        .catch(() => {
          if (!cancelled) {
            setSessions([]);
            setSummaries([]);
          }
        });
      return;
    }

    // all tab — 复用 reloadAll（SSE 轮询回退也走同一加载逻辑）
    reloadAll();
    return () => {
      cancelled = true;
    };
  }, [tab, search, typeFilter, currentSessionId, reloadAll]);

  const handleDelete = async (id: string) => {
    const api = window.electronAPI;
    if (!api?.memory) return;
    try {
      await api.memory.delete({ memory_id: id });
    } catch {
      // 后端删除失败时不本地移除，保持与事实一致
      return;
    }
    setMemories((prev) => prev.filter((m) => m.id !== id));
    setSummaries((prev) => prev.filter((m) => m.id !== id));
  };

  const handleSessionChange = async (sessionId: string) => {
    setSelectedSession(sessionId);
    const api = window.electronAPI;
    if (!api?.memory) return;
    try {
      const data = await api.memory.getSummary({ session_id: sessionId });
      if (mountedRef.current) {
        setSummaries(toItems((data as { summaries?: unknown } | undefined)?.summaries));
      }
    } catch {
      if (mountedRef.current) setSummaries([]);
    }
  };

  const showSearch = tab === 'all';

  return (
    <div className="flex-1 overflow-y-auto p-6 max-w-4xl mx-auto w-full">
      <h1 className="text-2xl font-bold mb-4">🧠 记忆管理</h1>

      <MemoryTabs active={tab} onChange={setTab} />

      {showSearch && (
        <div className="flex gap-2 mb-4">
          <div className="flex-1 flex items-center gap-2 border rounded px-3 py-2">
            <Search className="w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="搜索记忆..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="flex-1 outline-none text-sm"
              aria-label="搜索记忆"
            />
          </div>
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="border rounded px-3 text-sm"
            aria-label="按类型筛选"
          >
            {TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      )}

      {tab === 'summary' && (
        <div className="mb-4 flex items-center gap-2">
          <label htmlFor="session-select" className="text-sm text-gray-500">
            会话：
          </label>
          <select
            id="session-select"
            value={selectedSession}
            onChange={(e) => handleSessionChange(e.target.value)}
            className="border rounded px-3 py-1.5 text-sm max-w-sm"
          >
            {sessions.length === 0 && <option value="">（无会话）</option>}
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title || s.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </div>
      )}

      {tab === 'summary' ? (
        summaries.length === 0 ? (
          <p className="text-gray-500 text-center py-8">暂无会话摘要</p>
        ) : (
          summaries.map((m) => <MemoryCard key={m.id} memory={m} onDelete={handleDelete} />)
        )
      ) : memories.length === 0 ? (
        <p className="text-gray-500 text-center py-8">暂无记忆</p>
      ) : (
        memories.map((m) => <MemoryCard key={m.id} memory={m} onDelete={handleDelete} />)
      )}
    </div>
  );
}
