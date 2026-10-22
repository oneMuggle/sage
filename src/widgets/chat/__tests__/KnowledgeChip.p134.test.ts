import { describe, expect, it } from 'vitest';

import {
  evaluateKnowledgeChipAudit,
  exportKnowledgeChipAuditJson,
} from '../KnowledgeChip';

describe('KnowledgeChip audit diagnostics (Phase P134)', () => {
  it('validates high-relevance knowledge chip', () => {
    const report = evaluateKnowledgeChipAudit({
      sourceId: 'kb-42',
      label: 'Architecture Spec',
      relevanceScore: 0.86,
      clickable: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.relevancePct).toBe(86);
  });

  it('flags missing metadata and low relevance', () => {
    const parsed = JSON.parse(
      exportKnowledgeChipAuditJson({
        sourceId: '',
        label: ' ',
        relevanceScore: 0.05,
        clickable: false,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('missing_knowledge_source_id');
    expect(parsed.issueCodes).toContain('missing_knowledge_chip_label');
    expect(parsed.issueCodes).toContain('low_knowledge_relevance');
  });
});
