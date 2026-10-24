import { describe, expect, it } from 'vitest';

import { auditProjectCreationWizardGovernance } from '../ProjectCreationWizard';

describe('auditProjectCreationWizardGovernance (Phase P190)', () => {
  it('returns deterministic P190 governance audit payload', () => {
    const payload = JSON.parse(auditProjectCreationWizardGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('project-creation-wizard');
    expect(payload.phase).toBe('P190');
    expect(payload.audited).toBe(true);
  });
});
