import { describe, expect, it } from 'vitest';

import {
  auditJournalApiGovernance,
  formatJournalFillJson,
  formatJournalFillSummary,
} from '../journalApi';

describe('journalApi P176 governance audit', () => {
  it('audits journalApi governance contract and fill formatters', () => {
    const raw = auditJournalApiGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.api.journal_api.governance.v1');
    expect(parsed.phase).toBe('P176');
    expect(parsed.methods).toContain('fillFromContent');
    expect(formatJournalFillSummary(null)).toBe('journal-fill: empty');
    expect(JSON.parse(formatJournalFillJson({ spec_id: 'ieee' })).specId).toBe('ieee');
  });
});
