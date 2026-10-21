import { describe, expect, it } from 'vitest';

import { initialSettingsTab } from '../settingsNavigation';
import { formatSettingsNavigationJson, formatSettingsNavigationSummary } from '../settingsNavigation';
describe('settings initial navigation', () => {
  it('maps absent, hidden and invalid values to basic', () => {
    for (const value of [null, 'general', 'unknown', 'providers'])
      expect(initialSettingsTab(value)).toBe('basic');
  });
  it('retains valid bookmarks and gated providers', () => {
    expect(initialSettingsTab('models')).toBe('models');
    expect(initialSettingsTab('providers', true)).toBe('providers');
  });
  it('formats settings navigation summary and JSON (Phase P118)', () => {
    expect(formatSettingsNavigationSummary('general', false)).toBe(
      'general -> basic · providers=false',
    );
    expect(JSON.parse(formatSettingsNavigationJson('providers', true))).toEqual({
      requested: 'providers',
      resolved: 'providers',
      providersEnabled: true,
    });
  });
});
