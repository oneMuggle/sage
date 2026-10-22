import { describe, expect, it } from 'vitest';

import { auditUsePanelStoreGovernance, PANEL_STATE_KEY } from '../usePanelStore';

describe('usePanelStore P157 governance audit', () => {
  it('returns healthy defaults for usePanelStore governance', () => {
    const res = auditUsePanelStoreGovernance();
    expect(res.module).toBe('src/features/app-panels/usePanelStore.ts');
    expect(res.phase).toBe('P157');
    expect(res.stateKey).toBe(PANEL_STATE_KEY);
    expect(res.openSlotCount).toBe(2);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when openSlotCount exceeds 5', () => {
    const res = auditUsePanelStoreGovernance({ openSlotCount: 8 });
    expect(res.openSlotCount).toBe(8);
    expect(res.healthy).toBe(false);
  });
});
