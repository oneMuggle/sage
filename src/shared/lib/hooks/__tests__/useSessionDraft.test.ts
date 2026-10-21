import { describe, expect, it } from 'vitest';

import {
  formatSessionDraftSummary,
  formatSessionDraftJson,
} from '../useSessionDraft';

describe('useSessionDraft audit helpers', () => {
  it('formats session draft summary and json snapshot', () => {
    expect(formatSessionDraftSummary('sess-9', 'hello world')).toBe(
      'session=sess-9 · chars=11 · persisted=true',
    );
    const parsed = JSON.parse(formatSessionDraftJson('sess-9', 'hello world'));
    expect(parsed).toEqual({
      sessionId: 'sess-9',
      charCount: 11,
      persisted: true,
      storageKey: 'sage-drafts',
    });
  });

  it('handles nullish sessionId and draft safely', () => {
    expect(formatSessionDraftSummary(null, null)).toBe(
      'session=none · chars=0 · persisted=false',
    );
    expect(JSON.parse(formatSessionDraftJson('', undefined)).persisted).toBe(false);
  });
});
