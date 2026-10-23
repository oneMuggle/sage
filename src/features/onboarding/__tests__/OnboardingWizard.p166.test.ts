import { describe, expect, it } from 'vitest';

import { auditOnboardingWizardGovernance } from '../OnboardingWizard';

describe('auditOnboardingWizardGovernance (P166)', () => {
  it('returns compliant governance audit metadata for OnboardingWizard', () => {
    const report = auditOnboardingWizardGovernance();
    expect(report.module).toBe('src/features/onboarding/OnboardingWizard.tsx');
    expect(report.phase).toBe('P166');
    expect(report.domain).toBe('onboarding');
    expect(report.StepCount).toBe(2);
    expect(report.supportsConnectivityTest).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
