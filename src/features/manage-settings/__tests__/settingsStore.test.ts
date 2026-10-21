import { describe, expect, it } from 'vitest';

import {
  formatSettingsStoreJson,
  formatSettingsStoreSummary,
  useSettingsStore,
} from '../settingsStore';

describe('settingsStore audit helpers', () => {
  it('formats settings store summary', () => {
    const state = useSettingsStore.getState();
    expect(formatSettingsStoreSummary(state.settings, false)).toContain(
      'loading=false',
    );
  });

  it('serializes settings store audit JSON', () => {
    expect(
      JSON.parse(
        formatSettingsStoreJson(
          { endpoints: [], demoMode: true, version: '5.0' },
          false,
        ),
      ),
    ).toEqual({
      isLoading: false,
      endpointCount: 0,
      demoMode: true,
      version: '5.0',
    });
  });
});
