import { describe, expect, it } from 'vitest';

import { initialSettingsTab } from '../settingsNavigation';
import { formatSettingsNavigationJson, formatSettingsNavigationSummary } from '../settingsNavigation';
describe('settings initial navigation', () => {
  it('maps absent, hidden and invalid values to basic', () => {
    for (const value of [null, 'general', 'unknown'])
      expect(initialSettingsTab(value)).toBe('basic');
  });
  it('migrates merged tab keys to their new wrappers', () => {
    // P1-b: endpoints/models/providers → models-services; plugins/skills → plugins-skills
    expect(initialSettingsTab('endpoints')).toBe('models-services');
    expect(initialSettingsTab('models')).toBe('models-services');
    expect(initialSettingsTab('providers')).toBe('models-services');
    expect(initialSettingsTab('plugins')).toBe('plugins-skills');
    expect(initialSettingsTab('skills')).toBe('plugins-skills');
    expect(initialSettingsTab('models-services')).toBe('models-services');
    expect(initialSettingsTab('plugins-skills')).toBe('plugins-skills');
  });
  it('formats settings navigation summary and JSON (Phase P118)', () => {
    expect(formatSettingsNavigationSummary('general', false)).toBe(
      'general -> basic · providers=false',
    );
    expect(JSON.parse(formatSettingsNavigationJson('models-services', true))).toEqual({
      requested: 'models-services',
      resolved: 'models-services',
      providersEnabled: true,
    });
  });
});
