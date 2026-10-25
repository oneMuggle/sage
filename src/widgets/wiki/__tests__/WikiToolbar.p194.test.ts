import { describe, expect, it } from 'vitest';

import { auditWikiToolbarGovernance } from '../WikiToolbar';

describe('auditWikiToolbarGovernance (Phase P194)', () => {
  it('returns deterministic P194 governance audit payload', () => {
    const payload = JSON.parse(auditWikiToolbarGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('wiki-toolbar');
    expect(payload.phase).toBe('P194');
    expect(payload.audited).toBe(true);
  });
});
