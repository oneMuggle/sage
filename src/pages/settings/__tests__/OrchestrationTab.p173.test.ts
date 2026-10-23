import { describe, expect, it } from 'vitest';

import { auditOrchestrationTabGovernance } from '../OrchestrationTab';

describe('auditOrchestrationTabGovernance (P173)', () => {
  it('returns compliant governance audit metadata for OrchestrationTab', () => {
    const report = auditOrchestrationTabGovernance();
    expect(report.module).toBe('src/pages/settings/OrchestrationTab.tsx');
    expect(report.phase).toBe('P173');
    expect(report.domain).toBe('settings');
    expect(report.supportsWorktreeIsolationAndBudgetControls).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
