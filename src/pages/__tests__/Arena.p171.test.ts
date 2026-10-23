import { describe, expect, it } from 'vitest';

import { auditArenaPageGovernance } from '../Arena';

describe('auditArenaPageGovernance (P171)', () => {
  it('returns compliant governance audit metadata for Arena page', () => {
    const report = auditArenaPageGovernance();
    expect(report.module).toBe('src/pages/Arena.tsx');
    expect(report.phase).toBe('P171');
    expect(report.domain).toBe('pages');
    expect(report.tabs).toEqual(['accounts', 'register', 'draw']);
    expect(report.compliant).toBe(true);
  });
});
