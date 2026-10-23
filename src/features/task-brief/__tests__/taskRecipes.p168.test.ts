import { describe, expect, it } from 'vitest';

import { auditTaskRecipesGovernance } from '../taskRecipes';

describe('auditTaskRecipesGovernance (P168)', () => {
  it('returns compliant governance audit metadata for taskRecipes', () => {
    const report = auditTaskRecipesGovernance();
    expect(report.module).toBe('src/features/task-brief/taskRecipes.ts');
    expect(report.phase).toBe('P168');
    expect(report.domain).toBe('task-brief');
    expect(report.maxRecipes).toBe(64);
    expect(report.storageKey).toBe('sage:task-recipes:v1');
    expect(report.compliant).toBe(true);
  });
});
