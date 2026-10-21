import { describe, expect, it } from 'vitest';

import {
  formatZhSettingsAndModelsJson,
  formatZhSettingsAndModelsSummary,
  zhSettingsAndModels,
} from '../settingsAndModels';

describe('zhSettingsAndModels domain locale audit diagnostics', () => {
  it('formats zh.settingsAndModels summary', () => {
    const count = Object.keys(zhSettingsAndModels).length;
    expect(count).toBeGreaterThan(50);
    expect(formatZhSettingsAndModelsSummary()).toBe(
      `domain=zh.settingsAndModels · keys=${count}`,
    );
  });

  it('serializes zh.settingsAndModels audit JSON', () => {
    const parsed = JSON.parse(formatZhSettingsAndModelsJson());
    expect(parsed).toEqual({
      domain: 'zh.settingsAndModels',
      keyCount: Object.keys(zhSettingsAndModels).length,
    });
  });
});
