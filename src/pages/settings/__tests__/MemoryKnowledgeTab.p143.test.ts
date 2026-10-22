import { describe, expect, it } from 'vitest';

import { auditMemoryKnowledgeTabGovernance } from '../MemoryKnowledgeTab';

describe('MemoryKnowledgeTab P143 governance audit', () => {
  it('returns healthy defaults for MemoryKnowledgeTab governance', () => {
    const res = auditMemoryKnowledgeTabGovernance();
    expect(res.module).toBe('src/pages/settings/MemoryKnowledgeTab.tsx');
    expect(res.phase).toBe('P143');
    expect(res.memoryEnabled).toBe(true);
    expect(res.knowledgeSourcesCount).toBe(0);
    expect(res.autoIndexEnabled).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('normalizes knowledgeSourcesCount and toggle flags', () => {
    const res = auditMemoryKnowledgeTabGovernance({
      memoryEnabled: false,
      knowledgeSourcesCount: 9.7,
      autoIndexEnabled: false,
    });
    expect(res.memoryEnabled).toBe(false);
    expect(res.knowledgeSourcesCount).toBe(9);
    expect(res.autoIndexEnabled).toBe(false);
    expect(res.healthy).toBe(true);
  });
});
