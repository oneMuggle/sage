/**
 * r83: knowledgeApi 单元测试——知识库已被 wiki 替代，返回空态。
 */
import { describe, expect, it } from 'vitest';

import { knowledgeApi } from '../knowledgeApi';

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
