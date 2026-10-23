import { describe, expect, it } from 'vitest';

import { auditThemeGalleryGovernance } from '../ThemeGallery';

describe('auditThemeGalleryGovernance (P169)', () => {
  it('returns compliant governance audit metadata for ThemeGallery', () => {
    const report = auditThemeGalleryGovernance();
    expect(report.module).toBe('src/features/theme/ThemeGallery.tsx');
    expect(report.phase).toBe('P169');
    expect(report.domain).toBe('theme');
    expect(report.sections).toEqual(['basic', 'decorative']);
    expect(report.compliant).toBe(true);
  });
});
