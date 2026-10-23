import { describe, expect, it } from 'vitest';

import { auditBrandLogoGovernance } from '../BrandLogo';

describe('BrandLogo P149 governance audit', () => {
  it('returns healthy defaults for BrandLogo governance', () => {
    const res = auditBrandLogoGovernance();
    expect(res.module).toBe('src/shared/ui/BrandLogo.tsx');
    expect(res.phase).toBe('P149');
    expect(res.size).toBe('md');
    expect(res.animated).toBe(false);
    expect(res.healthy).toBe(true);
  });

  it('normalizes size and animated flag', () => {
    const res = auditBrandLogoGovernance({
      size: 'xl',
      animated: true,
    });
    expect(res.size).toBe('xl');
    expect(res.animated).toBe(true);
    expect(res.healthy).toBe(true);
  });
});
