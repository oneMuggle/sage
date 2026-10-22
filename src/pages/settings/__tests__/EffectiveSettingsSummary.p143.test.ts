import { describe, expect, it } from 'vitest';

import { auditEffectiveSettingsSummaryGovernance } from '../EffectiveSettingsSummary';

describe('EffectiveSettingsSummary P143 governance audit', () => {
  it('returns healthy defaults for EffectiveSettingsSummary governance', () => {
    const res = auditEffectiveSettingsSummaryGovernance();
    expect(res.module).toBe('src/pages/settings/EffectiveSettingsSummary.tsx');
    expect(res.phase).toBe('P143');
    expect(res.activeProvider).toBe('default');
    expect(res.permissionMode).toBe('workspace_write');
    expect(res.contextTurnLimit).toBe(20);
    expect(res.healthy).toBe(true);
  });

  it('normalizes provider, permissionMode, and contextTurnLimit', () => {
    const res = auditEffectiveSettingsSummaryGovernance({
      activeProvider: ' anthropic ',
      permissionMode: ' read_only ',
      contextTurnLimit: 35.8,
    });
    expect(res.activeProvider).toBe('anthropic');
    expect(res.permissionMode).toBe('read_only');
    expect(res.contextTurnLimit).toBe(35);
    expect(res.healthy).toBe(true);
  });
});
