import { describe, expect, it } from 'vitest';

import {
  enSettingsAndModels,
  formatEnSettingsAndModelsJson,
  formatEnSettingsAndModelsSummary,
} from '../settingsAndModels';

describe('enSettingsAndModels domain locale audit diagnostics', () => {
  it('formats en.settingsAndModels summary', () => {
    const count = Object.keys(enSettingsAndModels).length;
    expect(count).toBeGreaterThan(50);
    expect(formatEnSettingsAndModelsSummary()).toBe(
      `domain=en.settingsAndModels · keys=${count}`,
    );
  });

  it('serializes en.settingsAndModels audit JSON', () => {
    const parsed = JSON.parse(formatEnSettingsAndModelsJson());
    expect(parsed).toEqual({
      domain: 'en.settingsAndModels',
      keyCount: Object.keys(enSettingsAndModels).length,
    });
  });
});
