/**
 * r83: knowledgeApi 单元测试——知识库已被 wiki 替代，返回空态。
 */
import { describe, expect, it } from 'vitest';

import { formatKnowledgeDocsJson, formatKnowledgeDocsSummary, knowledgeApi } from '../knowledgeApi';

describe('knowledgeApi', () => {
  it('list() returns empty array (wiki replacement)', async () => {
    const r = await knowledgeApi.list();
    expect(r).toEqual([]);
  });

  it('search() returns empty array (wiki replacement)', async () => {
    const r = await knowledgeApi.search('query');
    expect(r).toEqual([]);
  });
});

describe('formatKnowledgeDocsSummary / formatKnowledgeDocsJson', () => {
  it('formats knowledge docs summary and JSON payload', () => {
    expect(formatKnowledgeDocsSummary([], 'architecture')).toBe(
      'knowledge-docs: 0 docs · query=architecture · legacy=wiki-replaced',
    );
    const payload = JSON.parse(formatKnowledgeDocsJson([], 'architecture'));
    expect(payload).toEqual({
      docCount: 0,
      query: 'architecture',
      wikiReplaced: true,
    });
  });
});
