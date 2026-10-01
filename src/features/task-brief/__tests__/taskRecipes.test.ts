import { beforeEach, describe, expect, it } from 'vitest';

import { readTaskRecipes, reviewTaskRecipe, saveTaskRecipe } from '../taskRecipes';
const brief = {
  scenario: 'report' as const,
  goal: 'Weekly report',
  audience: 'Team',
  sources: 'Approved notes',
  format: 'docx' as const,
  requirements: 'Review sources',
  projectId: null,
};
beforeEach(() => localStorage.clear());
describe('explicit task recipe persistence', () => {
  it('saves drafts without claiming execution or automatic verification', () => {
    const result = saveTaskRecipe(brief);
    expect(result.reviewedAt).toBeNull();
    expect(readTaskRecipes()[0].brief).toEqual(brief);
    reviewTaskRecipe(result.id);
    expect(readTaskRecipes()[0].reviewedAt).toEqual(expect.any(Number));
  });
  it('never overwrites unreadable or unsupported existing data', () => {
    const raw = JSON.stringify({ version: 99, recipes: [] });
    localStorage.setItem('sage:task-recipes:v1', raw);
    expect(() => saveTaskRecipe(brief)).toThrow();
    expect(localStorage.getItem('sage:task-recipes:v1')).toBe(raw);
  });
  it('requires a known recipe for explicit review', () => {
    expect(() => reviewTaskRecipe('unknown')).toThrow();
  });
});
