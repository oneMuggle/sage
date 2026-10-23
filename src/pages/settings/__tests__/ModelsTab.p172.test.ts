import { describe, expect, it } from 'vitest';

import { auditModelsTabGovernance } from '../ModelsTab';

describe('auditModelsTabGovernance (P172)', () => {
  it('returns compliant governance audit metadata for ModelsTab', () => {
    const report = auditModelsTabGovernance();
    expect(report.module).toBe('src/pages/settings/ModelsTab.tsx');
    expect(report.phase).toBe('P172');
    expect(report.domain).toBe('settings');
    expect(report.supportsAutoContextAndCatalogNavigation).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
