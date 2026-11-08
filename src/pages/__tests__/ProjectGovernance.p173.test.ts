import { describe, expect, it } from 'vitest';

import { auditProjectGovernancePageGovernance } from '../governance/governanceAudit';

describe('auditProjectGovernancePageGovernance (P173)', () => {
  it('governance page declares the five-tab layout', () => {
    const report = auditProjectGovernancePageGovernance();
    expect(report.module).toBe('src/pages/governance/GovernanceShell.tsx');
    expect(report.phase).toBe('P173');
    expect(report.domain).toBe('pages');
    expect(report.tabs).toEqual(['overview', 'rules', 'knowledge', 'files', 'settings']);
    expect(report.compliant).toBe(true);
  });
});
