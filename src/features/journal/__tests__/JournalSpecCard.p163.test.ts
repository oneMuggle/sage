import { describe, expect, it } from 'vitest';

import {
  auditJournalSpecCardGovernance,
  formatJournalSpecJson,
  formatJournalSpecMarkdown,
} from '../components/JournalSpecCard';

describe('JournalSpecCard governance audit (P163)', () => {
  it('returns ready governance status for JournalSpecCard', () => {
    const snap = auditJournalSpecCardGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/journal/components/JournalSpecCard.tsx',
      phase: 'P163',
      status: 'ready',
    });
  });

  it('formats journal spec markdown and json when null', () => {
    expect(formatJournalSpecMarkdown(null)).toContain('尚未选择模板');
    expect(JSON.parse(formatJournalSpecJson(null)).spec).toBeNull();
  });
});
