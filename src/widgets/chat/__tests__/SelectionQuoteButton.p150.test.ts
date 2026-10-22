import { describe, expect, it } from 'vitest';

import { auditSelectionQuoteButtonGovernance } from '../SelectionQuoteButton';

describe('SelectionQuoteButton P150 governance audit', () => {
  it('returns healthy defaults for SelectionQuoteButton governance', () => {
    const res = auditSelectionQuoteButtonGovernance();
    expect(res.module).toBe('src/widgets/chat/SelectionQuoteButton.tsx');
    expect(res.phase).toBe('P150');
    expect(res.selectionLength).toBe(48);
    expect(res.maxQuoteChars).toBe(2000);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when selectionLength is 0 or exceeds maxQuoteChars', () => {
    expect(auditSelectionQuoteButtonGovernance({ selectionLength: 0 }).healthy).toBe(false);
    expect(
      auditSelectionQuoteButtonGovernance({ selectionLength: 5000, maxQuoteChars: 1000 }).healthy,
    ).toBe(false);
  });
});
