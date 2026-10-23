import { describe, expect, it } from 'vitest';

import {
  auditStoreGovernance,
  formatStoreSessionJson,
  formatStoreSessionSummary,
} from '../store';

describe('store P180 governance audit', () => {
  it('audits store governance contract and session snapshot formatters', () => {
    const raw = auditStoreGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.store.governance.v1');
    expect(parsed.phase).toBe('P180');
    expect(parsed.emptySummary).toBe('0 sessions · current none · 0 messages');
    expect(formatStoreSessionSummary([], 's-1', 3)).toBe('0 sessions · current s-1 · 3 messages');
    expect(JSON.parse(formatStoreSessionJson([], 's-1', 3)).messageCount).toBe(3);
  });
});
