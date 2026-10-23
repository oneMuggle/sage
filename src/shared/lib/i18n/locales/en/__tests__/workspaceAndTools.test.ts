import { describe, expect, it } from 'vitest';

import {
  enWorkspaceAndTools,
  formatEnWorkspaceAndToolsJson,
  formatEnWorkspaceAndToolsSummary,
} from '../workspaceAndTools';

describe('enWorkspaceAndTools domain locale audit diagnostics', () => {
  it('formats en.workspaceAndTools summary', () => {
    const count = Object.keys(enWorkspaceAndTools).length;
    expect(count).toBeGreaterThan(50);
    expect(formatEnWorkspaceAndToolsSummary()).toBe(
      `domain=en.workspaceAndTools · keys=${count}`,
    );
  });

  it('serializes en.workspaceAndTools audit JSON', () => {
    const parsed = JSON.parse(formatEnWorkspaceAndToolsJson());
    expect(parsed).toEqual({
      domain: 'en.workspaceAndTools',
      keyCount: Object.keys(enWorkspaceAndTools).length,
    });
  });
});
