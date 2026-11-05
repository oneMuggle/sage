/**
 * Task 4.2: 记忆来源会话信息（标题 + 相对日期）解析。
 *
 * 记忆行只存 session_id，直接展示裸 ID 用户无法辨认来源。这里按 session_id
 * 懒加载 `GET /sessions/{id}`，模块级 Map 缓存 5 分钟（用户改标题后不会
 * 永久漂移），并且对失败的 id 缓存负结果，避免列表每次渲染都重复请求。
 *
 * `sessionApi.get()` 只接受 UUID 格式；历史/测试数据里的非 UUID id 会在
 * 发请求前直接抛错，由 catch 兜底为负结果 —— 调用方降级显示截断 ID。
 */
import { useEffect, useState } from 'react';

import { sessionApi } from '../../shared/api';

const SESSION_INFO_TTL_MS = 5 * 60 * 1000;

interface SessionInfoCacheEntry {
  title: string | null;
  createdAtMs: number | null;
  fetchedAt: number;
}

export interface SessionInfoState {
  title: string | null;
  createdAtMs: number | null;
  loading: boolean;
}

const cache = new Map<string, SessionInfoCacheEntry>();
const inflight = new Map<string, Promise<SessionInfoCacheEntry>>();

function readFreshCache(sessionId: string): SessionInfoCacheEntry | null {
  const cached = cache.get(sessionId);
  if (!cached) return null;
  if (Date.now() - cached.fetchedAt >= SESSION_INFO_TTL_MS) {
    cache.delete(sessionId);
    return null;
  }
  return cached;
}

/** 后端 created_at 是秒级时间戳；兼容已经是毫秒的值。 */
function normalizeCreatedAtMs(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return null;
  return value > 1e12 ? value : value * 1000;
}

export async function fetchSessionInfo(sessionId: string): Promise<SessionInfoCacheEntry> {
  const cached = readFreshCache(sessionId);
  if (cached) return cached;

  const pending = inflight.get(sessionId);
  if (pending) return pending;

  const request = (async () => {
    try {
      const session = await sessionApi.get(sessionId);
      const title =
        typeof session.title === 'string' && session.title.trim() ? session.title.trim() : null;
      const entry: SessionInfoCacheEntry = {
        title,
        createdAtMs: normalizeCreatedAtMs(session.created_at),
        fetchedAt: Date.now(),
      };
      cache.set(sessionId, entry);
      return entry;
    } catch {
      const entry: SessionInfoCacheEntry = {
        title: null,
        createdAtMs: null,
        fetchedAt: Date.now(),
      };
      cache.set(sessionId, entry);
      return entry;
    } finally {
      inflight.delete(sessionId);
    }
  })();

  inflight.set(sessionId, request);
  return request;
}

export function useSessionInfo(sessionId: string | undefined): SessionInfoState {
  const [state, setState] = useState<SessionInfoState>(() => {
    if (!sessionId) return { title: null, createdAtMs: null, loading: false };
    const cached = readFreshCache(sessionId);
    return cached
      ? { title: cached.title, createdAtMs: cached.createdAtMs, loading: false }
      : { title: null, createdAtMs: null, loading: true };
  });

  useEffect(() => {
    if (!sessionId) {
      setState({ title: null, createdAtMs: null, loading: false });
      return;
    }

    const cached = readFreshCache(sessionId);
    if (cached) {
      setState({ title: cached.title, createdAtMs: cached.createdAtMs, loading: false });
      return;
    }

    let cancelled = false;
    setState({ title: null, createdAtMs: null, loading: true });
    void fetchSessionInfo(sessionId).then((entry) => {
      if (!cancelled) {
        setState({ title: entry.title, createdAtMs: entry.createdAtMs, loading: false });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  return state;
}

/** 测试用：清空缓存，避免用例之间互相污染。 */
export function clearSessionInfoCache(): void {
  cache.clear();
  inflight.clear();
}
