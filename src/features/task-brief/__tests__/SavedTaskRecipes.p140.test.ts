import { describe, expect, it } from 'vitest';

import { evaluateSavedTaskRecipesGovernanceAudit } from '../SavedTaskRecipes';

describe('evaluateSavedTaskRecipesGovernanceAudit (Phase P140)', () => {
  it('returns healthy report for unique saved task recipes within capacity', () => {
    const report = evaluateSavedTaskRecipesGovernanceAudit({
      recipeIds: ['recipe-1', 'recipe-2', 'recipe-3'],
      maxRecipesAllowed: 50,
      hasOnUseHandler: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.uniqueRecipeCount).toBe(3);
    expect(report.withinCapacity).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags duplicate recipe IDs, exceeded capacity, and missing onUse handler', () => {
    const report = evaluateSavedTaskRecipesGovernanceAudit({
      recipeIds: ['recipe-1', 'recipe-1', 'recipe-2'],
      maxRecipesAllowed: 1,
      hasOnUseHandler: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'SAVED_TASK_RECIPES_DUPLICATE_ID',
      'SAVED_TASK_RECIPES_CAPACITY_EXCEEDED',
      'SAVED_TASK_RECIPES_USE_HANDLER_MISSING',
    ]);
  });
});
