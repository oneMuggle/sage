import { describe, expect, it } from 'vitest';

import {
  auditUseConfirmedPreferenceGovernance,
  formatConfirmedPreferenceJson,
  formatConfirmedPreferenceSummary,
} from '../useConfirmedPreference';

describe('useConfirmedPreference governance audit (P163)', () => {
  it('returns ready governance status for useConfirmedPreference', () => {
    const snap = auditUseConfirmedPreferenceGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/manage-settings/useConfirmedPreference.ts',
      phase: 'P163',
      status: 'ready',
    });
  });

  it('formats confirmed preference summary and json', () => {
    expect(formatConfirmedPreferenceSummary('ui.theme', 'saved', true)).toContain(
      'preference: ui.theme · status=saved · loaded',
    );
    expect(JSON.parse(formatConfirmedPreferenceJson('ui.theme', 'idle', false))).toEqual({
      key: 'ui.theme',
      status: 'idle',
      loaded: false,
    });
  });
});
