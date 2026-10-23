import { describe, expect, it } from 'vitest';

import {
  auditUseSessionDraftGovernance,
  formatSessionDraftJson,
  formatSessionDraftSummary,
} from '../useSessionDraft';

describe('useSessionDraft P181 governance audit', () => {
  it('audits useSessionDraft governance contract and session draft formatters', () => {
    const raw = auditUseSessionDraftGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.hooks.use_session_draft.governance.v1');
    expect(parsed.phase).toBe('P181');
    expect(parsed.storageKey).toBe('sage-drafts');
    expect(formatSessionDraftSummary('s1', 'hi')).toBe('session=s1 · chars=2 · persisted=true');
    expect(JSON.parse(formatSessionDraftJson('s1', 'hi')).charCount).toBe(2);
  });
});
