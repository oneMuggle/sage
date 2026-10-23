import { describe, expect, it } from 'vitest';

import {
  auditKnowledgeApiGovernance,
  formatKnowledgeDocsJson,
  formatKnowledgeDocsSummary,
} from '../knowledgeApi';

describe('knowledgeApi P176 governance audit', () => {
  it('audits knowledgeApi governance contract and legacy wiki replacement state', () => {
    const raw = auditKnowledgeApiGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.api.knowledge_api.governance.v1');
    expect(parsed.phase).toBe('P176');
    expect(parsed.wikiReplaced).toBe(true);
    expect(formatKnowledgeDocsSummary([], 'test')).toContain('legacy=wiki-replaced');
    expect(JSON.parse(formatKnowledgeDocsJson([], 'test')).wikiReplaced).toBe(true);
  });
});
