/**
 * Sage API - Memory API
 */

import { invoke } from './desktopInvoke';
import type { Memory } from './types';
import { ApiException, handleApiError, sanitizeInput, withRetry } from './utils';

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
   * 获取记忆列表
   */
  async getMemories(
    memoryType?: 'episodic' | 'semantic',
    page: number = 1,
    pageSize: number = 20,
  ): Promise<Memory[]> {
    // 验证分页参数
    const safePage = Math.max(1, Number(page) || 1);
    const safePageSize = Math.min(100, Math.max(1, Number(pageSize) || 20));

    return withRetry(async () => {
      try {
        return await invoke<Memory[]>('get_memories', {
          memoryType: memoryType || null,
          page: safePage,
          pageSize: safePageSize,
        });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },
};
