import { describe, expect, it } from 'vitest';

import { auditUseStudioStateGovernance } from '../useStudioState';

describe('auditUseStudioStateGovernance (P166)', () => {
  it('returns compliant governance audit metadata for useStudioState', () => {
    const report = auditUseStudioStateGovernance();
    expect(report.module).toBe('src/features/project-type/useStudioState.ts');
    expect(report.phase).toBe('P166');
    expect(report.domain).toBe('project-type');
    expect(report.defaultArchetype).toBe('coding');
    expect(report.supportsImmutableProjectPatch).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
