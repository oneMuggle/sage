import { describe, expect, it } from 'vitest';

import { auditZoteroClientGovernance } from '../zoteroClient';

describe('zoteroClient P146 governance audit', () => {
  it('returns healthy defaults for zoteroClient governance', () => {
    const res = auditZoteroClientGovernance();
    expect(res.module).toBe('src/shared/api/zoteroClient.ts');
    expect(res.phase).toBe('P146');
    expect(res.connected).toBe(true);
    expect(res.indexedItemCount).toBe(0);
    expect(res.healthy).toBe(true);
  });

  it('normalizes connected flag and indexedItemCount', () => {
    const res = auditZoteroClientGovernance({
      connected: false,
      indexedItemCount: 42.3,
    });
    expect(res.connected).toBe(false);
    expect(res.indexedItemCount).toBe(42);
    expect(res.healthy).toBe(false);
  });
});
