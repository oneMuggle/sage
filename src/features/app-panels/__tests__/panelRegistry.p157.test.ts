import { describe, expect, it } from 'vitest';

import {
  auditPanelRegistryGovernance,
  PANEL_DEFINITIONS,
  PANEL_SLOT_IDS,
} from '../panelRegistry';

describe('panelRegistry P157 governance audit', () => {
  it('returns healthy defaults for panelRegistry governance', () => {
    const res = auditPanelRegistryGovernance();
    expect(res.module).toBe('src/features/app-panels/panelRegistry.ts');
    expect(res.phase).toBe('P157');
    expect(res.slotCount).toBe(PANEL_SLOT_IDS.length);
    expect(res.panelCount).toBe(PANEL_DEFINITIONS.length);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when slotCount or panelCount is 0', () => {
    const res = auditPanelRegistryGovernance({
      slotCount: 0,
      panelCount: 0,
    });
    expect(res.slotCount).toBe(0);
    expect(res.panelCount).toBe(0);
    expect(res.healthy).toBe(false);
  });
});
