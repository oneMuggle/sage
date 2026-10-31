import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  bondDays,
  normalizePetProfile,
  readPetProfile,
  recordPat,
  writePetProfile,
} from '../pet/profile';

const DAY = 24 * 60 * 60 * 1000;
const NOW = 1_700_000_000_000;

describe('pet profile', () => {
  it('starts the bond on first read and sanitizes garbage', () => {
    const profile = normalizePetProfile({ patCount: -3, firstSeenAt: 'nope' }, NOW);
    expect(profile.firstSeenAt).toBe(NOW);
    expect(profile.patCount).toBe(0);
    expect(profile.lastPatAt).toBeNull();
  });

  it('counts pats and computes bond days', () => {
    const profile = normalizePetProfile({ firstSeenAt: NOW - 2 * DAY, patCount: 4 }, NOW);
    expect(bondDays(profile, NOW)).toBe(3);
    const patted = recordPat(profile, NOW);
    expect(patted.patCount).toBe(5);
    expect(patted.lastPatAt).toBe(NOW);
  });

  it('round-trips through disk', () => {
    const dir = mkdtempSync(join(tmpdir(), 'sage-pet-profile-'));
    const file = join(dir, 'pet-profile.json');
    try {
      const initial = readPetProfile(file, NOW);
      expect(initial.firstSeenAt).toBe(NOW);
      const patted = recordPat(initial, NOW + 1000);
      expect(writePetProfile(file, patted)).toBe(true);
      expect(readPetProfile(file, NOW + 2000)).toEqual(patted);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
