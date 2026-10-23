import { describe, expect, it } from 'vitest';

import { auditSavedTaskRecipesGovernance } from '../SavedTaskRecipes';

describe('auditSavedTaskRecipesGovernance (P168)', () => {
  it('returns compliant governance audit metadata for SavedTaskRecipes', () => {
    const report = auditSavedTaskRecipesGovernance();
    expect(report.module).toBe('src/features/task-brief/SavedTaskRecipes.tsx');
    expect(report.phase).toBe('P168');
    expect(report.domain).toBe('task-brief');
    expect(report.supportsManualReviewRecording).toBe(true);
    expect(report.supportsRecipeReuse).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
