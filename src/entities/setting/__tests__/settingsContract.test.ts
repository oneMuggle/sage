import { describe, expect, it } from 'vitest';

import { settingsRegistry } from '../settingsRegistry';
import { DEFAULT_SETTINGS } from '../types';

describe('settings contract', () => {
  it('keeps core defaults aligned with the registry', () => {
    expect(settingsRegistry.streaming.defaultValue).toBe(DEFAULT_SETTINGS.streaming);
    expect(settingsRegistry.autoMemory.defaultValue).toBe(DEFAULT_SETTINGS.autoMemory);
    expect(settingsRegistry.confirmDelete.defaultValue).toBe(DEFAULT_SETTINGS.confirmDelete);
    expect(settingsRegistry.maxContext.defaultValue).toBe(DEFAULT_SETTINGS.maxContext);
    expect(settingsRegistry.autoContext.defaultValue).toBe(DEFAULT_SETTINGS.autoContext);
    expect(settingsRegistry.temperature.defaultValue).toBe(DEFAULT_SETTINGS.temperature);
    expect(settingsRegistry['orch.maxConcurrentSubagents'].defaultValue).toBe(
      DEFAULT_SETTINGS.orch.maxConcurrentSubagents,
    );
  });

  it('does not expose credential-bearing keys in searchable registry metadata', () => {
    const searchable = Object.values(settingsRegistry).filter(
      (metadata) => metadata.visibility !== 'internal',
    );
    expect(
      searchable.some((metadata) => /api.?key|password/i.test(metadata.label)),
    ).toBe(false);
  });

  it('marks dangerous or delayed settings with non-basic visibility or risk', () => {
    expect(settingsRegistry.network_policy.riskLevel).toBe('high');
    expect(settingsRegistry.permission_mode.riskLevel).toBe('high');
    expect(settingsRegistry['updates.updateServerUrl'].visibility).toBe('advanced');
    expect(settingsRegistry['orch.maxConcurrentSubagents'].applyMode).toBe('next-run');
  });
});
