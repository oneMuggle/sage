import { describe, expect, it } from 'vitest';

import { auditWelcomePageGovernance } from '../Welcome';

describe('auditWelcomePageGovernance (P172)', () => {
  it('returns compliant governance audit metadata for Welcome page', () => {
    const report = auditWelcomePageGovernance();
    expect(report.module).toBe('src/pages/Welcome.tsx');
    expect(report.phase).toBe('P172');
    expect(report.domain).toBe('pages');
    expect(report.supportsRecommendationsAndSavedRecipes).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
