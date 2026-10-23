import { describe, expect, it } from 'vitest';

import {
  ENABLE_UPDATE_PROVIDERS_UI,
  formatUpdateFeatureFlagSummary,
  formatUpdateFeatureFlagJson,
} from '../updateFeatureFlag';

describe('updateFeatureFlag audit helpers', () => {
  it('formats feature flag summary and json', () => {
    expect(ENABLE_UPDATE_PROVIDERS_UI()).toBe(true);
    expect(formatUpdateFeatureFlagSummary(true)).toBe('updateProvidersUi=enabled');
    expect(formatUpdateFeatureFlagSummary(false)).toBe('updateProvidersUi=disabled');
    expect(JSON.parse(formatUpdateFeatureFlagJson(false))).toEqual({
      updateProvidersUi: false,
    });
  });

  it('falls back to runtime feature flag when nullish', () => {
    expect(formatUpdateFeatureFlagSummary(null)).toBe('updateProvidersUi=enabled');
    expect(JSON.parse(formatUpdateFeatureFlagJson(undefined)).updateProvidersUi).toBe(true);
  });
});
