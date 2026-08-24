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
 */

import { invoke } from './desktopInvoke';
import type { Memory, MemoryListResponse } from './types';
import { ApiException, handleApiError, sanitizeInput, withRetry } from './utils';

/**
 * 类型守卫:把后端响应规整成 ``MemoryListResponse``。
 *
 * Task 2 起 ``/memory/list`` 返回 envelope ``{items, total, page, ...}``,
 * 但旧 caller 可能直接拿返回当数组用。防御性地兼容旧 flat list 形态:
 * 把传入数组就地包成 envelope,避免下游解构 ``.items`` 时崩溃。
 */
function coerceMemoryListResponse(raw: unknown): MemoryListResponse {
  if (raw && typeof raw === 'object' && !Array.isArray(raw) && 'items' in raw) {
    return raw as MemoryListResponse;
  }
  if (Array.isArray(raw)) {
    return {
      items: raw as Memory[],
      total: raw.length,
      page: 1,
      page_size: raw.length,
      layer: 'all',
      source_breakdown: { episodic: 0, semantic: 0 },
    };
  }
  return {
    items: [],
    total: 0,
    page: 1,
    page_size: 0,
    layer: 'all',
    source_breakdown: { episodic: 0, semantic: 0 },
  };
}

export const memoryApi = {
  /**
   * 搜索记忆
   */
  async searchMemories(query: string, memoryType?: 'episodic' | 'semantic'): Promise<Memory[]> {
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
   * 获取记忆列表(Task 2 起返回 envelope)。
   *
   * Backwards-compat:如果后端误返回旧 flat list,自动包成 envelope,避免
   * ``resp.items`` undefined 引起 UI 崩溃。详见 ``coerceMemoryListResponse``。
   */
  async getMemories(
    memoryType?: 'episodic' | 'semantic',
    page: number = 1,
    pageSize: number = 20,
  ): Promise<MemoryListResponse> {
    // 验证分页参数
    const safePage = Math.max(1, Number(page) || 1);
    const safePageSize = Math.min(100, Math.max(1, Number(pageSize) || 20));

    return withRetry(async () => {
      try {
        const raw = await invoke<unknown>('get_memories', {
          memoryType: memoryType || null,
          page: safePage,
          pageSize: safePageSize,
        });
        return coerceMemoryListResponse(raw);
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },
};
