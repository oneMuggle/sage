import { describe, expect, it } from 'vitest';

import {
  auditJournalContentEditorGovernance,
  formatJournalContentDraftJson,
  formatJournalContentDraftSummary,
} from '../components/JournalContentEditor';

describe('JournalContentEditor governance audit (P163)', () => {
  it('returns ready governance status for JournalContentEditor', () => {
    const snap = auditJournalContentEditorGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/journal/components/JournalContentEditor.tsx',
      phase: 'P163',
      status: 'ready',
    });
  });

  it('formats journal content draft summary and json', () => {
    const draft = { title: ' Test ', abstract: ' Abstract ' };
    expect(formatJournalContentDraftSummary(draft, true)).toContain('titleLen=4');
    expect(JSON.parse(formatJournalContentDraftJson(draft, false))).toMatchObject({
      titleLength: 4,
      abstractLength: 8,
      disabled: false,
    });
  });
});
