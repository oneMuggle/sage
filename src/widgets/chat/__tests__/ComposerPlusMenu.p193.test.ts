import { describe, expect, it } from 'vitest';

import { auditComposerPlusMenuGovernance } from '../ComposerPlusMenu';

describe('auditComposerPlusMenuGovernance (Phase P193)', () => {
  it('returns deterministic P193 governance audit payload', () => {
    const payload = JSON.parse(auditComposerPlusMenuGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('composer-plus-menu');
    expect(payload.phase).toBe('P193');
    expect(payload.audited).toBe(true);
  });
});
