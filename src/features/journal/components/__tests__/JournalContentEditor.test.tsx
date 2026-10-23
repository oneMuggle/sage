import { describe, expect, it } from 'vitest';

import {
  formatJournalContentDraftJson,
  formatJournalContentDraftSummary,
} from '../JournalContentEditor';

describe('JournalContentEditor audit helpers', () => {
  it('formats journal content draft summary', () => {
    expect(
      formatJournalContentDraftSummary(
        { title: 'Paper', abstract: 'Summary text' },
        false,
      ),
    ).toBe('titleLen=5 · abstractLen=12 · disabled=false');
  });

  it('exports journal content draft JSON snapshot', () => {
    expect(
      JSON.parse(
        formatJournalContentDraftJson({ title: 'A', abstract: 'BC' }, true),
      ),
    ).toEqual({
      titleLength: 1,
      abstractLength: 2,
      disabled: true,
    });
  });
});

