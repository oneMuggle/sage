import { describe, expect, it } from 'vitest';

import { auditProjectGovernancePageGovernance } from '../ProjectGovernance';

describe('auditProjectGovernancePageGovernance (P173)', () => {
  it('returns compliant governance audit metadata for ProjectGovernance page', () => {
    const report = auditProjectGovernancePageGovernance();
    expect(report.module).toBe('src/pages/ProjectGovernance.tsx');
    expect(report.phase).toBe('P173');
    expect(report.domain).toBe('pages');
    expect(report.tabs).toEqual(['overview', 'knowledge', 'settings']);
    expect(report.compliant).toBe(true);
  });
});
