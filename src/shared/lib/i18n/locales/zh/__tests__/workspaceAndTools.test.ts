import { describe, expect, it } from 'vitest';

import {
  formatZhWorkspaceAndToolsJson,
  formatZhWorkspaceAndToolsSummary,
  zhWorkspaceAndTools,
} from '../workspaceAndTools';

describe('zhWorkspaceAndTools domain locale audit diagnostics', () => {
  it('formats zh.workspaceAndTools summary', () => {
    const count = Object.keys(zhWorkspaceAndTools).length;
    expect(count).toBeGreaterThan(50);
    expect(formatZhWorkspaceAndToolsSummary()).toBe(
      `domain=zh.workspaceAndTools · keys=${count}`,
    );
  });

  it('serializes zh.workspaceAndTools audit JSON', () => {
    const parsed = JSON.parse(formatZhWorkspaceAndToolsJson());
    expect(parsed).toEqual({
      domain: 'zh.workspaceAndTools',
      keyCount: Object.keys(zhWorkspaceAndTools).length,
    });
  });
});
