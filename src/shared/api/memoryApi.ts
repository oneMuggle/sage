/**
 * Sage API - Memory API
 *
 * Task 2 (Win7 parity):
 * - ``getMemories`` 现在返回 ``MemoryListResponse``(envelope)而不是裸数组,
 *   与后端 ``/memory/list`` 契约一致。``items`` 字段携带记忆列表。
 * - 每条 ``Memory`` 新增可选 ``layer`` / ``source`` / ``created_at_ms``
 *   字段;UI 按这些字段决定展示分组。
 * - ``searchMemories`` / ``saveMemory`` 沿用旧 ``Memory[]`` / ``Memory``
 *   契约 — 后端工具侧契约修复对前端 IPC 入口透明。
 *
 * 批次三 step 6 (spec §4.3 line 150):
 * - ``getMemories`` 新增可选 ``offset`` 与 ``sessionId`` 参数,直接透传
 *   后端的 offset cursor 与 session 隔离过滤。
 * - 新增 ``getSessionSummaries(sessionId)`` 调用 ``/memory/summaries``
 *   拿到会话摘要列表(跨 session 视图在 spec step 5 严令禁止,所以这个
 *   方法 ``sessionId`` 必填)。
 * - ``MemoryLayer`` 扩展到 ``'working'`` / ``'session_summary'``,UI 按
 *   ``source`` 字段决定徽章样式。
 */

import { isDemoMode, searchDemoMemories } from './demoInterceptors';
import { invoke } from './desktopInvoke';
import type { Memory, MemoryListResponse, MemorySummariesListResponse } from './types';
import { ApiException, handleApiError, sanitizeInput, withRetry } from './utils';

const MEMORY_LAYERS = ['episodic', 'semantic', 'working', 'session_summary', 'all'] as const;

type MemoryLayer = (typeof MEMORY_LAYERS)[number];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asNonNegativeInteger(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : fallback;
}

function asPositiveInteger(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 ? value : fallback;
}

function asLayer(value: unknown, fallback: MemoryLayer): MemoryLayer {
  return typeof value === 'string' && (MEMORY_LAYERS as readonly string[]).includes(value)
    ? (value as MemoryLayer)
    : fallback;
}

const VALID_MEMORY_LAYERS: ReadonlySet<Memory['layer']> = new Set([
  'episodic',
  'semantic',
  'working',
  'session_summary',
]);

const VALID_MEMORY_SOURCES: ReadonlySet<Memory['source']> = new Set([
  'episodic',
  'semantic',
  'working',
  'session_summary',
]);

const VALID_MEMORY_TYPES: ReadonlySet<Memory['memory_type']> = new Set([
  'episodic',
  'semantic',
  'working',
  'session_summary',
]);

const VALID_SUMMARY_STATUSES: ReadonlySet<NonNullable<Memory['status']>> = new Set([
  'pending',
  'ready',
  'failed',
]);

function asOptionalString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

function asNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}

/**
 * 单条 Memory 的元素级 narrow(spec §4.3 step 6 强化)。
 *
 * 后端按契约应给完整 envelope,但 renderer 必须 **不信任** 任何字段:
 * 缺字段或类型错不抛错,而是用 fallback,保证 UI 永远不会因为一条坏行
 * 整体崩溃。同时根据 layer/source/memory_type 决定是否清掉 status /
 * error_message(session_summary 之外不该携带)。
 */
function coerceMemoryItem(raw: unknown): Memory {
  const empty: Memory = {
    id: '',
    content: '',
    importance: 0,
    tags: [],
    created_at: 0,
    access_count: 0,
  };
  if (!isRecord(raw)) {
    return empty;
  }
  const id = asOptionalString(raw.id) ?? '';
  const content = asOptionalString(raw.content) ?? '';
  const summary = asOptionalString(raw.summary);
  const memoryTypeRaw = asOptionalString(raw.memory_type);
  const layerRaw = asOptionalString(raw.layer);
  const sourceRaw = asOptionalString(raw.source);
  const memoryType =
    memoryTypeRaw && VALID_MEMORY_TYPES.has(memoryTypeRaw as Memory['memory_type'])
      ? (memoryTypeRaw as Memory['memory_type'])
      : undefined;
  const layer =
    layerRaw && VALID_MEMORY_LAYERS.has(layerRaw as Memory['layer'])
      ? (layerRaw as Memory['layer'])
      : memoryType;
  const source =
    sourceRaw && VALID_MEMORY_SOURCES.has(sourceRaw as Memory['source'])
      ? (sourceRaw as Memory['source'])
      : layer;
  const sessionId = asOptionalString(raw.session_id);
  const sourceTurnId = asOptionalString(raw.source_turn_id);
  const statusRaw = asOptionalString(raw.status);
  const status =
    statusRaw && VALID_SUMMARY_STATUSES.has(statusRaw as NonNullable<Memory['status']>)
      ? (statusRaw as NonNullable<Memory['status']>)
      : undefined;
  const errorMessage = status === 'failed' ? asOptionalString(raw.error_message) : undefined;

  const createdAt = asNumber(raw.created_at, 0);
  const createdAtMs = asNumber(raw.created_at_ms, createdAt > 0 ? createdAt * 1000 : 0);
  const accessedAt = asNumber(raw.accessed_at, 0);
  const accessCount = asNumber(raw.access_count, 0);

  return {
    id,
    content,
    summary,
    memory_type: memoryType,
    layer,
    source,
    session_id: sessionId,
    source_turn_id: sourceTurnId,
    status,
    error_message: errorMessage,
    importance: asNumber(raw.importance, 0),
    tags: asStringArray(raw.tags),
    created_at: createdAt,
    created_at_ms: createdAtMs > 0 ? createdAtMs : undefined,
    accessed_at: accessedAt > 0 ? accessedAt : undefined,
    access_count: accessCount,
  };
}

function coerceMemoryListResponse(raw: unknown): MemoryListResponse {
  if (Array.isArray(raw)) {
    const items = (raw as unknown[]).map(coerceMemoryItem);
    return {
      items,
      total: items.length,
      page: 1,
      page_size: items.length,
      offset: 0,
      layer: 'all',
      source_breakdown: { episodic: 0, semantic: 0, working: 0, session_summary: 0 },
    };
  }
  if (!isRecord(raw)) {
    return {
      items: [],
      total: 0,
      page: 1,
      page_size: 0,
      offset: 0,
      layer: 'all',
      source_breakdown: { episodic: 0, semantic: 0, working: 0, session_summary: 0 },
    };
  }

  const items = Array.isArray(raw.items) ? (raw.items as unknown[]).map(coerceMemoryItem) : [];
  const breakdown = isRecord(raw.source_breakdown) ? raw.source_breakdown : {};
  return {
    items,
    total: asNonNegativeInteger(raw.total, items.length),
    page: asPositiveInteger(raw.page, 1),
    page_size: asNonNegativeInteger(raw.page_size, items.length),
    offset: asNonNegativeInteger(raw.offset, 0),
    layer: asLayer(raw.layer, 'all'),
    source_breakdown: {
      working: asNonNegativeInteger(breakdown.working, 0),
      session_summary: asNonNegativeInteger(breakdown.session_summary, 0),
      episodic: asNonNegativeInteger(breakdown.episodic, 0),
      semantic: asNonNegativeInteger(breakdown.semantic, 0),
    },
  };
}

function coerceSummariesListResponse(raw: unknown): MemorySummariesListResponse {
  const fallback: MemorySummariesListResponse = {
    session_id: '',
    items: [],
    total: 0,
    page: 1,
    page_size: 0,
    offset: 0,
  };
  if (!isRecord(raw)) {
    return fallback;
  }
  const sessionId = typeof raw.session_id === 'string' ? raw.session_id : '';
  const items = Array.isArray(raw.items) ? (raw.items as unknown[]).map(coerceMemoryItem) : [];
  // spec §4.3 step 5:session_id 必须一致;否则视为坏响应,扔掉 items,
  // 防止"我在看会话 A、列表给我返回会话 B 的摘要"的串味。
  const consistent = items.every((m) => !m.session_id || m.session_id === sessionId);
  return {
    session_id: sessionId,
    items: consistent ? items : [],
    total: consistent ? asNonNegativeInteger(raw.total, items.length) : 0,
    page: asPositiveInteger(raw.page, 1),
    page_size: asNonNegativeInteger(raw.page_size, consistent ? items.length : 0),
    offset: asNonNegativeInteger(raw.offset, 0),
  };
}

export const memoryApi = {
  /**
   * 搜索记忆
   */
  async searchMemories(query: string, memoryType?: 'episodic' | 'semantic'): Promise<Memory[]> {
    // 演示模式 (2026-08-27): 关键词包含匹配过滤 demo 集合
    if (isDemoMode()) {
      return searchDemoMemories(query, memoryType);
    }
    // 安全化查询输入
    const safeQuery = sanitizeInput(query);

    return withRetry(async () => {
      try {
        return await invoke<Memory[]>('search_memory', {
          query: safeQuery,
          memoryType: memoryType || null,
          limit: 20,
        });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * 保存记忆
   */
  async saveMemory(
    content: string,
    memoryType: 'episodic' | 'semantic',
    importance: number = 5,
    tags?: string[],
  ): Promise<Memory> {
    // 安全化内容输入
    const safeContent = sanitizeInput(content);
    const safeTags = Array.isArray(tags) ? tags.map((t) => sanitizeInput(t)) : [];

    // 验证重要性值
    const safeImportance = Math.min(10, Math.max(0, Number(importance) || 5));

    return withRetry(async () => {
      try {
        return await invoke<Memory>('save_memory', {
          content: safeContent,
          memoryType,
          importance: safeImportance,
          tags: safeTags,
        });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * 删除记忆
   */
  async deleteMemory(id: string): Promise<void> {
    // 验证记忆ID
    if (!id || typeof id !== 'string') {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: '无效的记忆ID',
        details: { memoryId: id },
      });
    }

    return withRetry(async () => {
      try {
        await invoke('delete_memory', { id });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * 获取记忆列表(Task 2 起返回 envelope;step 6 起支持 offset / sessionId)。
   *
   * Backwards-compat:如果后端误返回旧 flat list,自动包成 envelope,避免
   * ``resp.items`` undefined 引起 UI 崩溃。详见 ``coerceMemoryListResponse``。
   *
   * ``memoryType`` 取值扩展到 ``'working'`` / ``'session_summary'`` /
   * ``'all'``(step 6 起 ``'all'`` 是默认,合并四层)。
   * ``sessionId`` 透传到后端做 session 隔离(spec step 5 严禁跨 session 串味)。
   * ``offset`` 透传后端 offset cursor,避免调用方自己再做 page→offset 换算。
   */
  async getMemories(
    memoryType?: 'episodic' | 'semantic' | 'working' | 'session_summary' | 'all',
    page: number = 1,
    pageSize: number = 20,
    options?: { offset?: number; sessionId?: string | null; signal?: AbortSignal },
  ): Promise<MemoryListResponse> {
    // 验证分页参数
    const safePage = Math.max(1, Number(page) || 1);
    const safePageSize = Math.min(100, Math.max(1, Number(pageSize) || 20));
    const safeOffset =
      options?.offset !== undefined && options.offset !== null
        ? Math.max(0, Math.floor(Number(options.offset) || 0))
        : null;
    const safeSessionId =
      options?.sessionId && typeof options.sessionId === 'string' && options.sessionId.trim()
        ? options.sessionId.trim()
        : null;

    return withRetry(async () => {
      try {
        if (options?.signal?.aborted) {
          throw new DOMException('Aborted', 'AbortError');
        }
        const raw = await invoke<unknown>('get_memories', {
          memoryType: memoryType || null,
          page: safePage,
          pageSize: safePageSize,
          offset: safeOffset,
          sessionId: safeSessionId,
        });
        if (options?.signal?.aborted) {
          throw new DOMException('Aborted', 'AbortError');
        }
        return coerceMemoryListResponse(raw);
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * 获取指定会话的摘要列表(批次三 step 6 新增,spec §4.3 line 150)。
   *
   * ``sessionId`` 必填 — spec step 5 严禁"全部 session 的摘要"视图,所以
   * 这里强行校验,空串直接抛参数错。
   *
   * 返回的 ``items`` 已包含 ``source='session_summary'`` / ``status`` /
   * ``error_message``,UI 可直接按 ``status`` 渲染失败徽章。
   */
  async getSessionSummaries(
    sessionId: string,
    page: number = 1,
    pageSize: number = 20,
    options?: { signal?: AbortSignal },
  ): Promise<MemorySummariesListResponse> {
    if (!sessionId || typeof sessionId !== 'string' || !sessionId.trim()) {
      throw new ApiException({
        error: 'VALIDATION_ERROR',
        message: 'session_id is required for /memory/summaries',
        details: { sessionId },
      });
    }
    const safePage = Math.max(1, Number(page) || 1);
    const safePageSize = Math.min(100, Math.max(1, Number(pageSize) || 20));

    return withRetry(async () => {
      try {
        if (options?.signal?.aborted) {
          throw new DOMException('Aborted', 'AbortError');
        }
        const raw = await invoke<unknown>('get_session_summaries', {
          sessionId: sessionId.trim(),
          page: safePage,
          pageSize: safePageSize,
        });
        if (options?.signal?.aborted) {
          throw new DOMException('Aborted', 'AbortError');
        }
        return coerceSummariesListResponse(raw);
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },
};
