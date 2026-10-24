import { describe, expect, it } from 'vitest';

import { auditConstraintEditorGovernance } from '../ConstraintEditor';

describe('auditConstraintEditorGovernance (Phase P189)', () => {
  it('returns deterministic P189 governance audit payload', () => {
    const payload = JSON.parse(auditConstraintEditorGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('constraint-editor');
    expect(payload.phase).toBe('P189');
    expect(payload.audited).toBe(true);
  });
});
