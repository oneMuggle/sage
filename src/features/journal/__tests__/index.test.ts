import { describe, expect, it } from 'vitest';

import {
  formatJournalBarrelJson,
  formatJournalBarrelSummary,
} from '../index';

describe('journal barrel audit helpers', () => {
  it('formats journal barrel summary', () => {
    expect(formatJournalBarrelSummary()).toBe(
      'module=features/journal · exports=JournalPanel,useJournalTemplates · count=2',
    );
  });

  it('exports journal barrel JSON snapshot', () => {
    const parsed = JSON.parse(formatJournalBarrelJson());
    expect(parsed.count).toBe(2);
    expect(parsed.exports).toContain('JournalPanel');
  });
});

