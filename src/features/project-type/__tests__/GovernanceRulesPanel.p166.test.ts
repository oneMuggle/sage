import { describe, expect, it } from 'vitest';

import { auditGovernanceRulesPanelGovernance } from '../GovernanceRulesPanel';

describe('auditGovernanceRulesPanelGovernance (P166)', () => {
  it('returns compliant governance audit metadata for GovernanceRulesPanel', () => {
    const report = auditGovernanceRulesPanelGovernance();
    expect(report.module).toBe('src/features/project-type/GovernanceRulesPanel.tsx');
    expect(report.phase).toBe('P166');
    expect(report.domain).toBe('project-type');
    expect(report.sections).toEqual(['constraints', 'allowed-paths']);
    expect(report.supportsMarkdownAndJsonExport).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
