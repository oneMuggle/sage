import { describe, expect, it } from 'vitest';

import {
  AtEntityMenu,
  auditAtEntityMenuGovernance,
  formatAtEntityMenuJson,
} from '../AtEntityMenu';

describe('AtEntityMenu governance audit (P159)', () => {
  it('verifies AtEntityMenu component and summary formatter readiness', () => {
    const report = auditAtEntityMenuGovernance();
    expect(report.module).toBe('features.chat.AtEntityMenu');
    expect(report.phase).toBe('P159');
    expect(report.hasMenuComponent).toBe(true);
    expect(report.hasSummaryFormatter).toBe(true);
    expect(report.healthy).toBe(true);
    expect(typeof AtEntityMenu).toBe('function');
  });

  it('serializes JSON audit output for entity query', () => {
    const raw = formatAtEntityMenuJson('wiki:overview');
    expect(JSON.parse(raw)).toBeTruthy();
  });
});
