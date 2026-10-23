import { describe, expect, it } from 'vitest';

import { auditPromptTemplatesTabGovernance } from '../PromptTemplatesTab';

describe('auditPromptTemplatesTabGovernance (P173)', () => {
  it('returns compliant governance audit metadata for PromptTemplatesTab', () => {
    const report = auditPromptTemplatesTabGovernance();
    expect(report.module).toBe('src/pages/settings/PromptTemplatesTab.tsx');
    expect(report.phase).toBe('P173');
    expect(report.domain).toBe('settings');
    expect(report.supportsOrphanTemplateMemoryCleanup).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
