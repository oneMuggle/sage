/**
 * Sage API - Knowledge API
 */

import { invoke } from './desktopInvoke';
import type { KnowledgeDoc } from './types';
import { handleApiError, sanitizeInput, withRetry } from './utils';

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
    const safeQuery = sanitizeInput(query);
    return withRetry(async () => {
      try {
        return await invoke<KnowledgeDoc[]>('search_knowledge_docs', {
          query: safeQuery,
          category: category || null,
        });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },
};
