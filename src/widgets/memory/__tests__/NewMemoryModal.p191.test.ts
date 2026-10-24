import { describe, expect, it } from 'vitest';

import { auditNewMemoryModalGovernance } from '../NewMemoryModal';

describe('auditNewMemoryModalGovernance (Phase P191)', () => {
  it('returns deterministic P191 governance audit payload', () => {
    const payload = JSON.parse(auditNewMemoryModalGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('new-memory-modal');
    expect(payload.phase).toBe('P191');
    expect(payload.audited).toBe(true);
  });
});
