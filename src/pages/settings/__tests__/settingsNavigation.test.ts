import { describe, expect, it } from 'vitest';

import { initialSettingsTab } from '../settingsNavigation';
describe('settings initial navigation', () => {
  it('maps absent, hidden and invalid values to basic', () => {
    for (const value of [null, 'general', 'unknown', 'providers'])
      expect(initialSettingsTab(value)).toBe('basic');
  });
  it('retains valid bookmarks and gated providers', () => {
    expect(initialSettingsTab('models')).toBe('models');
    expect(initialSettingsTab('providers', true)).toBe('providers');
  });
});
