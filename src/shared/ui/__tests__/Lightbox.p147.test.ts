import { describe, expect, it } from 'vitest';

import { auditLightboxGovernance } from '../Lightbox/Lightbox';

describe('Lightbox P147 governance audit', () => {
  it('returns healthy defaults for Lightbox governance', () => {
    const res = auditLightboxGovernance();
    expect(res.module).toBe('src/shared/ui/Lightbox/Lightbox.tsx');
    expect(res.phase).toBe('P147');
    expect(res.zoomScale).toBe(1);
    expect(res.hasValidSrc).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('clamps zoomScale and checks hasValidSrc', () => {
    const res = auditLightboxGovernance({
      zoomScale: 9,
      hasValidSrc: false,
    });
    expect(res.zoomScale).toBe(4);
    expect(res.hasValidSrc).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
