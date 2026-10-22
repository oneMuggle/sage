import { describe, expect, it } from 'vitest';

import { auditWindowControlsGovernance } from '../WindowControls';

describe('WindowControls P150 governance audit', () => {
  it('returns healthy defaults for WindowControls governance', () => {
    const res = auditWindowControlsGovernance();
    expect(res.module).toBe('src/widgets/layout/WindowControls.tsx');
    expect(res.phase).toBe('P150');
    expect(res.hasBridge).toBe(true);
    expect(res.maximized).toBe(false);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when hasBridge is false', () => {
    const res = auditWindowControlsGovernance({
      hasBridge: false,
      maximized: true,
    });
    expect(res.hasBridge).toBe(false);
    expect(res.maximized).toBe(true);
    expect(res.healthy).toBe(false);
  });
});
