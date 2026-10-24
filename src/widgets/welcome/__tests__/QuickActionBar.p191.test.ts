import { describe, expect, it } from 'vitest';

import { auditQuickActionBarGovernance } from '../QuickActionBar';

describe('auditQuickActionBarGovernance (Phase P191)', () => {
  it('returns deterministic P191 governance audit payload', () => {
    const payload = JSON.parse(auditQuickActionBarGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('quick-action-bar');
    expect(payload.phase).toBe('P191');
    expect(payload.audited).toBe(true);
  });
});
