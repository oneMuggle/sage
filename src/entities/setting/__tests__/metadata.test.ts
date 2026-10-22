import { describe, expect, it } from 'vitest';

import {
  APPLY_MODE_LABELS,
  formatSettingMetadataJson,
  formatSettingMetadataSummary,
  RISK_LEVEL_LABELS,
} from '../metadata';

describe('setting metadata audit helpers', () => {
  it('formats setting metadata summary and exposes label maps', () => {
    expect(APPLY_MODE_LABELS.immediate.en).toBe('Immediate');
    expect(RISK_LEVEL_LABELS.high.color).toBe('red');
    expect(
      formatSettingMetadataSummary({
        key: 'llm.temperature',
        scope: 'session',
        applyMode: 'next-request',
        riskLevel: 'medium',
      }),
    ).toBe('llm.temperature · session · next-request · risk=medium');
  });

  it('serializes setting metadata audit JSON', () => {
    expect(
      JSON.parse(
        formatSettingMetadataJson({
          key: 'app.demoMode',
          scope: 'global',
          storage: 'local',
          applyMode: 'restart',
          visibility: 'developer',
          riskLevel: 'high',
        }),
      ),
    ).toEqual({
      key: 'app.demoMode',
      scope: 'global',
      storage: 'local',
      applyMode: 'restart',
      visibility: 'developer',
      riskLevel: 'high',
    });
  });
});
