import { describe, expect, it } from 'vitest';

import {
  AtFileMenu,
  auditAtFileMenuGovernance,
  formatAtFileMenuJson,
} from '../AtFileMenu';

describe('AtFileMenu governance audit (P159)', () => {
  it('verifies AtFileMenu component and markdown formatter contract', () => {
    const report = auditAtFileMenuGovernance();
    expect(report.module).toBe('features.chat.AtFileMenu');
    expect(report.phase).toBe('P159');
    expect(report.hasMenuComponent).toBe(true);
    expect(report.hasMarkdownFormatter).toBe(true);
    expect(report.healthy).toBe(true);
    expect(typeof AtFileMenu).toBe('function');
  });

  it('serializes JSON audit output for file menu state', () => {
    const raw = formatAtFileMenuJson('README.md', [], '/workspace');
    expect(JSON.parse(raw)).toBeTruthy();
  });
});
