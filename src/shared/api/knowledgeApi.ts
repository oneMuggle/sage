/**
 * Sage API - Knowledge API
 */

import { invoke } from './desktopInvoke';
import type { KnowledgeDoc } from './types';
import { handleApiError, withRetry } from './utils';

export const knowledgeApi = {
  async list(): Promise<KnowledgeDoc[]> {
    return withRetry(async () => {
      try {
        return await invoke<KnowledgeDoc[]>('list_knowledge_docs');
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  async search(query: string, category?: string): Promise<KnowledgeDoc[]> {
    // 查询词原文直传: 转义会破坏检索匹配 (如含 < / & 的代码片段查询)
    return withRetry(async () => {
      try {
        return await invoke<KnowledgeDoc[]>('search_knowledge_docs', {
          query,
          category: category || null,
        });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },
};
