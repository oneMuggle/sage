import { describe, expect, it } from 'vitest';

import { auditMemorySettingsTabGovernance } from '../MemorySettingsTab';

describe('MemorySettingsTab P143 governance audit', () => {
  it('returns healthy defaults for MemorySettingsTab governance', () => {
    const res = auditMemorySettingsTabGovernance();
    expect(res.module).toBe('src/pages/settings/MemorySettingsTab.tsx');
    expect(res.phase).toBe('P143');
    expect(res.retentionDays).toBe(90);
    expect(res.autoCaptureEnabled).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('clamps retentionDays to positive integers', () => {
    const res = auditMemorySettingsTabGovernance({
      retentionDays: 0,
      autoCaptureEnabled: false,
    });
    expect(res.retentionDays).toBe(1);
    expect(res.autoCaptureEnabled).toBe(false);
    expect(res.healthy).toBe(true);
  });
});
