import { describe, expect, it } from 'vitest';

import { auditTitlebarGovernance } from '../Titlebar';

describe('Titlebar P150 governance audit', () => {
  it('returns healthy defaults for Titlebar governance', () => {
    const res = auditTitlebarGovernance();
    expect(res.module).toBe('src/widgets/layout/Titlebar.tsx');
    expect(res.phase).toBe('P150');
    expect(res.heightPx).toBe(36);
    expect(res.showWindowControls).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('clamps heightPx between 28 and 64', () => {
    expect(auditTitlebarGovernance({ heightPx: 120 }).heightPx).toBe(64);
    expect(auditTitlebarGovernance({ heightPx: 10 }).heightPx).toBe(28);
  });
});
