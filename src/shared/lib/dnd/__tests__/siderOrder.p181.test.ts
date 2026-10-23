import { describe, expect, it } from 'vitest';

import {
  areSiderOrdersEqual,
  auditSiderOrderGovernance,
  formatSiderOrderJson,
  formatSiderOrderSummary,
  reorderSiderIds,
} from '../siderOrder';

describe('siderOrder P181 governance audit', () => {
  it('audits siderOrder governance contract and order helpers', () => {
    const raw = auditSiderOrderGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.dnd.sider_order.governance.v1');
    expect(parsed.phase).toBe('P181');
    expect(parsed.reorderedSample).toEqual(['b', 'c', 'a']);
    expect(areSiderOrdersEqual(['x', 'y'], ['x', 'y'])).toBe(true);
    expect(reorderSiderIds(['x', 'y'], 1, 0)).toEqual(['y', 'x']);
    expect(formatSiderOrderSummary(['x', 'y'])).toBe('count=2 · ids=[x,y]');
    expect(JSON.parse(formatSiderOrderJson(['x'])).count).toBe(1);
  });
});
