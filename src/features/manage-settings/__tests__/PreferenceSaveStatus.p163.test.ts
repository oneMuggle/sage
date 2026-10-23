import { describe, expect, it } from 'vitest';

import {
  auditPreferenceSaveStatusGovernance,
  formatPreferenceSaveStatusJson,
  formatPreferenceSaveStatusSummary,
} from '../PreferenceSaveStatus';

describe('PreferenceSaveStatus governance audit (P163)', () => {
  it('returns ready governance status for PreferenceSaveStatus', () => {
    const snap = auditPreferenceSaveStatusGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/manage-settings/PreferenceSaveStatus.tsx',
      phase: 'P163',
      status: 'ready',
    });
  });

  it('formats preference save status summary and json', () => {
    expect(formatPreferenceSaveStatusSummary('saved')).toContain('status=saved · visible=true');
    expect(JSON.parse(formatPreferenceSaveStatusJson('error'))).toEqual({
      status: 'error',
      visible: true,
      role: 'alert',
    });
  });
});
