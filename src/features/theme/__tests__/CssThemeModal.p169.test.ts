import { describe, expect, it } from 'vitest';

import { auditCssThemeModalGovernance } from '../CssThemeModal';

describe('auditCssThemeModalGovernance (P169)', () => {
  it('returns compliant governance audit metadata for CssThemeModal', () => {
    const report = auditCssThemeModalGovernance();
    expect(report.module).toBe('src/features/theme/CssThemeModal.tsx');
    expect(report.phase).toBe('P169');
    expect(report.domain).toBe('theme');
    expect(report.allowedVariableCount).toBe(16);
    expect(report.supportsLiveCssPreview).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
