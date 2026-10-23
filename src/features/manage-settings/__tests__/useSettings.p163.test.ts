import { describe, expect, it } from 'vitest';

import { DEFAULT_SETTINGS } from '../../../entities/setting/types';
import {
  auditUseSettingsGovernance,
  formatUseSettingsSnapshotJson,
  formatUseSettingsSnapshotSummary,
} from '../useSettings';

describe('useSettings governance audit (P163)', () => {
  it('returns ready governance status for useSettings', () => {
    const snap = auditUseSettingsGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/manage-settings/useSettings.ts',
      phase: 'P163',
      status: 'ready',
    });
  });

  it('formats useSettings snapshot summary and json', () => {
    expect(formatUseSettingsSnapshotSummary(DEFAULT_SETTINGS, false)).toContain('ready');
    expect(JSON.parse(formatUseSettingsSnapshotJson(DEFAULT_SETTINGS, true))).toMatchObject({
      isLoading: true,
      maxContext: DEFAULT_SETTINGS.maxContext,
    });
  });
});
