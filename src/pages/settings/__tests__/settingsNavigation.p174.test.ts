import { describe, expect, it } from 'vitest';

import { auditSettingsNavigationGovernance } from '../settingsNavigation';

describe('auditSettingsNavigationGovernance (P174)', () => {
  it('returns compliant governance audit metadata for settingsNavigation', () => {
    const report = auditSettingsNavigationGovernance();
    expect(report.module).toBe('src/pages/settings/settingsNavigation.ts');
    expect(report.phase).toBe('P174');
    expect(report.domain).toBe('settings');
    expect(report.legacyAliases).toEqual([
      'general->basic',
      'endpoints->models-services',
      'models->models-services',
      'providers->models-services',
      'plugins->plugins-skills',
      'skills->plugins-skills',
      'memory-knowledge->memory',
    ]);
    expect(report.compliant).toBe(true);
  });
});
