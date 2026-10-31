import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  DEFAULT_PET_CONFIG,
  mergePetConfig,
  normalizePetConfig,
  readPetConfig,
  writePetConfig,
} from '../pet/config';

describe('pet config', () => {
  it('returns defaults for garbage input', () => {
    expect(normalizePetConfig(null)).toEqual(DEFAULT_PET_CONFIG);
    expect(normalizePetConfig('nope')).toEqual(DEFAULT_PET_CONFIG);
    expect(normalizePetConfig({ enabled: 'yes', size: 42 })).toEqual(DEFAULT_PET_CONFIG);
  });

  it('keeps valid values and rejects unknown enums', () => {
    const config = normalizePetConfig({
      enabled: true,
      displayMode: 'both',
      size: 'gigantic',
      tempo: 'lively',
      bubbleMode: 'always',
      compatibilityMode: 'on',
      petPack: '  custom  ',
    });
    expect(config.enabled).toBe(true);
    expect(config.displayMode).toBe('both');
    expect(config.size).toBe('medium');
    expect(config.tempo).toBe('lively');
    expect(config.bubbleMode).toBe('always');
    expect(config.compatibilityMode).toBe('on');
    expect(config.petPack).toBe('custom');
  });

  it('merges nested sound scenes without dropping other settings', () => {
    const merged = mergePetConfig(DEFAULT_PET_CONFIG, {
      size: 'large',
      soundScenes: { error: true },
    });
    expect(merged.size).toBe('large');
    expect(merged.soundScenes).toEqual({ waiting: true, error: true, done: false });
    expect(merged.bubbleMode).toBe(DEFAULT_PET_CONFIG.bubbleMode);
  });

  it('round-trips through disk and falls back on missing files', () => {
    const dir = mkdtempSync(join(tmpdir(), 'sage-pet-config-'));
    const file = join(dir, 'pet-config.json');
    try {
      expect(readPetConfig(file)).toEqual(DEFAULT_PET_CONFIG);
      const changed = mergePetConfig(DEFAULT_PET_CONFIG, { enabled: true, size: 'small' });
      expect(writePetConfig(file, changed)).toBe(true);
      expect(readPetConfig(file)).toEqual(changed);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
