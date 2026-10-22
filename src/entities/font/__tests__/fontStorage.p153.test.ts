import { describe, expect, it } from 'vitest';

import { auditFontStorageGovernance, FONT_STORAGE_KEY } from '../fontStorage';

describe('fontStorage P153 governance audit', () => {
  it('returns healthy defaults for fontStorage governance', () => {
    const res = auditFontStorageGovernance();
    expect(res.module).toBe('src/entities/font/fontStorage.ts');
    expect(res.phase).toBe('P153');
    expect(res.storageKey).toBe(FONT_STORAGE_KEY);
    expect(res.hasPersistedPayload).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when storageKey mismatches or hasPersistedPayload is false', () => {
    const res = auditFontStorageGovernance({
      storageKey: 'legacy-key',
      hasPersistedPayload: false,
    });
    expect(res.storageKey).toBe('legacy-key');
    expect(res.hasPersistedPayload).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
