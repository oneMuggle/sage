import { describe, expect, it } from 'vitest';

import { auditAgentsPageGovernance } from '../Agents';

describe('auditAgentsPageGovernance (P171)', () => {
  it('returns compliant governance audit metadata for Agents page', () => {
    const report = auditAgentsPageGovernance();
    expect(report.module).toBe('src/pages/Agents.tsx');
    expect(report.phase).toBe('P171');
    expect(report.domain).toBe('pages');
    expect(report.supportsAgentToggleAndEdit).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
