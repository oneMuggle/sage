import { describe, expect, it } from 'vitest';

import {
  formatJournalActionsJson,
  formatJournalActionsSummary,
} from '../JournalActions';

describe('JournalActions audit helpers', () => {
  it('formats journal actions summary', () => {
    expect(formatJournalActionsSummary(true, false, false)).toBe(
      'hasSpec=true · loading=false · error=false',
    );
    expect(formatJournalActionsSummary(false, true, true)).toBe(
      'hasSpec=false · loading=true · error=true',
    );
  });

  it('exports journal actions JSON snapshot', () => {
    expect(JSON.parse(formatJournalActionsJson(true, false, true))).toEqual({
      hasSpec: true,
      loading: false,
      hasError: true,
    });
  });
});

