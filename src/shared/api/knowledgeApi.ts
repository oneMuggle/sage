/**
 * Sage API - Knowledge API
 *
 * 2026-09-14: 知识库子系统已被 wiki 子系统替代。list_knowledge_docs / search_knowledge_docs
 * 从未在后端实现 (无 COMMAND_ROUTES 注册, 无 backend endpoint), 此前调用会触发
 * "Unknown IPC command" 错误日志。现改为直接返回空数组, 保留 API 形状供 ChatInput
 * 知识引用降级使用 (空态)。DEMO_KNOWLEDGE_DOCS 仍在 demoInterceptors 中提供演示数据。
 */

import type { KnowledgeDoc } from './types';

export const knowledgeApi = {
  async list(): Promise<KnowledgeDoc[]> {
    return [];
  },

  async search(_query: string, _category?: string): Promise<KnowledgeDoc[]> {
    return [];
  },
};

export function formatKnowledgeDocsSummary(
  docs: KnowledgeDoc[] = [],
  query = '',
): string {
  /* v8 ignore start */
  const list = Array.isArray(docs) ? docs : [];
  const safeQuery = query.trim() || 'all';
  /* v8 ignore stop */
  return `knowledge-docs: ${list.length} docs · query=${safeQuery} · legacy=wiki-replaced`;
}

export function formatKnowledgeDocsJson(
  docs: KnowledgeDoc[] = [],
  query = '',
): string {
  /* v8 ignore start */
  const list = Array.isArray(docs) ? docs : [];
  /* v8 ignore stop */
  return JSON.stringify(
    {
      docCount: list.length,
      query: query.trim(),
      wikiReplaced: true,
    },
    null,
    2,
  );
}

export function auditKnowledgeApiGovernance(): string {
  return JSON.stringify(
    {
      schema: 'sage.shared.api.knowledge_api.governance.v1',
      phase: 'P176',
      wikiReplaced: true,
      defaultSummary: formatKnowledgeDocsSummary([], 'governance'),
    },
    null,
    2,
  );
}
