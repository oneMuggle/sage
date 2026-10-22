import { describe, expect, it } from 'vitest';

import { auditMemoryPageGovernance } from '../../Memory';

describe('Memory P142 governance audit', () => {
  it('returns healthy defaults for Memory page governance', () => {
    const res = auditMemoryPageGovernance();
    expect(res.module).toBe('src/pages/Memory.tsx');
    expect(res.phase).toBe('P142');
    expect(res.entryCount).toBe(0);
    expect(res.activeCategory).toBe('all');
    expect(res.isSearching).toBe(false);
    expect(res.healthy).toBe(true);
  });

  it('normalizes entryCount and activeCategory', () => {
    const res = auditMemoryPageGovernance({
      entryCount: 18.6,
      activeCategory: ' preferences ',
      isSearching: true,
    });
    expect(res.entryCount).toBe(18);
    expect(res.activeCategory).toBe('preferences');
    expect(res.isSearching).toBe(true);
    expect(res.healthy).toBe(true);
  });
});
