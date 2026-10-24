import { describe, expect, it } from 'vitest';

import { auditSkillAuditDrawerGovernance } from '../SkillAuditDrawer';

describe('auditSkillAuditDrawerGovernance (Phase P192)', () => {
  it('returns deterministic P192 governance audit payload', () => {
    const payload = JSON.parse(auditSkillAuditDrawerGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('skill-audit-drawer');
    expect(payload.phase).toBe('P192');
    expect(payload.audited).toBe(true);
  });
});
