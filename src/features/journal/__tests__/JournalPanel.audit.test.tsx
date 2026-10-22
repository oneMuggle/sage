import { describe, expect, it } from 'vitest';

import {
  formatJournalPanelJson,
  formatJournalPanelSummary,
} from '../JournalPanel';

describe('JournalPanel audit helpers', () => {
  it('formats journal panel summary', () => {
    expect(formatJournalPanelSummary('/repo', 2, 1)).toBe(
      'workspace=bound · errors=2 · warnings=1',
    );
    expect(formatJournalPanelSummary('', -1, -2)).toBe(
      'workspace=unbound · errors=0 · warnings=0',
    );
  });

  it('exports journal panel JSON snapshot', () => {
    expect(JSON.parse(formatJournalPanelJson('/repo', 1, 3))).toEqual({
      workspaceBound: true,
      errorCount: 1,
      warningCount: 3,
    });
  });
});

