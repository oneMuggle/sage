import { describe, expect, it } from 'vitest';

import {
  auditSettingsStoreGovernance,
  formatSettingsStoreJson,
  formatSettingsStoreSummary,
} from '../settingsStore';

describe('settingsStore governance audit (P163)', () => {
  it('returns ready governance status for settingsStore', () => {
    const snap = auditSettingsStoreGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/manage-settings/settingsStore.ts',
      phase: 'P163',
      status: 'ready',
    });
  });

  it('formats settings store summary and json', () => {
    expect(formatSettingsStoreSummary({}, false)).toContain('loading=false');
    expect(JSON.parse(formatSettingsStoreJson({}, true))).toMatchObject({
      isLoading: true,
      endpointCount: 0,
    });
  });
});
