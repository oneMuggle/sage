import { describe, expect, it } from 'vitest';

import {
  auditChangesListStoreGovernance,
  buildChangesListStoreAuditJson,
  CHANGES_FETCH_DEBOUNCE_MS,
} from '../changesListStore';

describe('changesListStore governance audit (P159)', () => {
  it('verifies changes list store debounce and hook health', () => {
    const report = auditChangesListStoreGovernance();
    expect(report.module).toBe('features.changes.changesListStore');
    expect(report.phase).toBe('P159');
    expect(report.debounceMs).toBe(CHANGES_FETCH_DEBOUNCE_MS);
    expect(report.hasStoreHook).toBe(true);
    expect(report.healthy).toBe(true);
  });

  it('maintains JSON audit helper serialization', () => {
    const raw = buildChangesListStoreAuditJson();
    expect(JSON.parse(raw)).toBeTruthy();
  });
});
