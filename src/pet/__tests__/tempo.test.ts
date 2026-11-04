import { describe, expect, it } from 'vitest';

import { idleDelayMs } from '../engine/tempo';

describe('idle pacing', () => {
  it('uses the quiet/standard/lively ranges', () => {
    expect(idleDelayMs('quiet', () => 0)).toBe(45_000);
    expect(idleDelayMs('quiet', () => 1)).toBe(90_000);
    expect(idleDelayMs('standard', () => 0)).toBe(25_000);
    expect(idleDelayMs('lively', () => 1)).toBe(22_000);
  });

  it('falls back to standard for unknown tempo', () => {
    expect(idleDelayMs('unknown', () => 0)).toBe(25_000);
  });
});
