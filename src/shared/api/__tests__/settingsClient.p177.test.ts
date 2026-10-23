import { describe, expect, it } from 'vitest';

import {
  auditSettingsClientGovernance,
  formatPreferenceSnapshotJson,
  formatPreferenceSnapshotSummary,
  LOAD_TIMEOUT_MS,
} from '../settingsClient';

describe('settingsClient P177 governance audit', () => {
  it('audits settingsClient governance contract and preference snapshot formatters', () => {
    const raw = auditSettingsClientGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.api.settings_client.governance.v1');
    expect(parsed.phase).toBe('P177');
    expect(parsed.loadTimeoutMs).toBe(LOAD_TIMEOUT_MS);
    expect(formatPreferenceSnapshotSummary('theme_mode', 'dark', 'ui')).toBe('ui:theme_mode · dark');
    expect(JSON.parse(formatPreferenceSnapshotJson('theme_mode', 'dark', 'ui')).hasValue).toBe(true);
  });
});
