import { describe, expect, it } from 'vitest';

import { settingsRegistry } from '../../../entities/setting/settingsRegistry';
import { validateSettingValue } from '../../../entities/setting/settingsValidation';

describe('settings registry contract', () => {
  it('registers public settings with complete metadata', () => {
    const publicSettings = Object.values(settingsRegistry).filter(
      (item) => item.visibility !== 'internal',
    );
    expect(publicSettings.length).toBeGreaterThan(30);
    for (const item of publicSettings) {
      expect(item.key).toBeTruthy();
      expect(item.description).toBeTruthy();
      expect(item.defaultValue).not.toBeUndefined();
      expect(item.storage).toMatch(/^(app_settings|preference|electron|local)$/);
    }
  });

  it('rejects zero concurrent subagents', () => {
    expect(validateSettingValue('orch.maxConcurrentSubagents', 0)).toContain('小于 1');
    expect(validateSettingValue('orch.maxConcurrentSubagents', 1)).toBeNull();
  });

  it('includes all update config fields', () => {
    expect(Object.keys(settingsRegistry)).toEqual(
      expect.arrayContaining([
        'updates.updateStrategy',
        'updates.channel',
        'updates.rollbackWindowDays',
        'updates.autoRollbackThreshold',
        'updates.checkIntervalHours',
        'updates.updateServerUrl',
        'updates.enableTelemetry',
        'updates.cacheRetentionDays',
      ]),
    );
  });
});
