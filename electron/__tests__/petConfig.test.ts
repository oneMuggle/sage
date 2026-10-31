import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  DEFAULT_PET_CONFIG,
  MAX_PETS,
  mergePetConfig,
  normalizePetConfig,
  readPetConfig,
  writePetConfig,
} from '../pet/config';

describe('pet config v2', () => {
  it('returns defaults for garbage input', () => {
    expect(normalizePetConfig(null)).toEqual(DEFAULT_PET_CONFIG);
    expect(normalizePetConfig('nope')).toEqual(DEFAULT_PET_CONFIG);
    expect(normalizePetConfig({ enabled: 'yes', pets: 'nope' })).toEqual(DEFAULT_PET_CONFIG);
  });

  it('keeps valid values and rejects unknown enums', () => {
    const config = normalizePetConfig({
      enabled: true,
      displayMode: 'both',
      tempo: 'lively',
      bubbleMode: 'always',
      compatibilityMode: 'on',
      pets: [{ id: 'default', petPack: '  custom  ', size: 'large' }],
    });
    expect(config.version).toBe(2);
    expect(config.enabled).toBe(true);
    expect(config.displayMode).toBe('both');
    expect(config.tempo).toBe('lively');
    expect(config.bubbleMode).toBe('always');
    expect(config.compatibilityMode).toBe('on');
    expect(config.pets).toEqual([{ id: 'default', petPack: 'custom', size: 'large' }]);
  });

  it('migrates a v1 single-pet config', () => {
    const config = normalizePetConfig({
      version: 1,
      enabled: true,
      petPack: 'my-pack',
      size: 'small',
      tempo: 'quiet',
    });
    expect(config.version).toBe(2);
    expect(config.pets).toEqual([{ id: 'default', petPack: 'my-pack', size: 'small' }]);
    expect(config.tempo).toBe('quiet');
  });

  it('caps the list, replaces duplicate/invalid ids and keeps valid sizes', () => {
    const config = normalizePetConfig({
      pets: [
        { id: 'a', petPack: 'p1', size: 'mini' },
        { id: 'a', petPack: 'p2', size: 'bogus' },
        { id: '../bad', petPack: 'p3', size: 'huge' },
        { id: 'd', petPack: 'p4', size: 'small' },
      ],
    });
    expect(config.pets).toHaveLength(MAX_PETS);
    expect(new Set(config.pets.map((pet) => pet.id)).size).toBe(MAX_PETS);
    expect(config.pets[1]).toMatchObject({ petPack: 'p2', size: 'medium' });
    expect(config.pets[2]?.petPack).toBe('p3');
  });

  it('falls back to one default pet when every entry is invalid', () => {
    expect(normalizePetConfig({ pets: [null, 1, 'x'] }).pets).toEqual([
      { id: 'default', petPack: 'dafeiyu', size: 'medium' },
    ]);
  });
});

describe('mergePetConfig', () => {
  it('merges nested sound scenes and global settings', () => {
    const merged = mergePetConfig(DEFAULT_PET_CONFIG, {
      tempo: 'lively',
      soundScenes: { error: true },
    });
    expect(merged.tempo).toBe('lively');
    expect(merged.soundScenes).toEqual({ waiting: true, error: true, done: false });
    expect(merged.bubbleMode).toBe(DEFAULT_PET_CONFIG.bubbleMode);
  });

  it('applies legacy petPack/size patches to the first pet only', () => {
    const base = normalizePetConfig({
      pets: [
        { id: 'default', petPack: 'a', size: 'medium' },
        { id: 'pet-2', petPack: 'b', size: 'small' },
      ],
    });
    const merged = mergePetConfig(base, { petPack: 'c', size: 'large' });
    expect(merged.pets[0]).toEqual({ id: 'default', petPack: 'c', size: 'large' });
    expect(merged.pets[1]).toEqual({ id: 'pet-2', petPack: 'b', size: 'small' });
  });

  it('replaces the pets array and normalizes untrusted entries', () => {
    const merged = mergePetConfig(DEFAULT_PET_CONFIG, {
      pets: [
        { id: 'a', petPack: 'one', size: 'huge' },
        { id: 'a', petPack: 'two', size: 'bogus' },
      ],
    });
    expect(merged.pets).toHaveLength(2);
    expect(merged.pets[0]).toEqual({ id: 'a', petPack: 'one', size: 'huge' });
    expect(merged.pets[1]).toMatchObject({ petPack: 'two', size: 'medium' });
    expect(merged.pets[1]?.id).not.toBe('a');
  });

  it('ignores non-object patches', () => {
    expect(mergePetConfig(DEFAULT_PET_CONFIG, null)).toBe(DEFAULT_PET_CONFIG);
    expect(mergePetConfig(DEFAULT_PET_CONFIG, 'x')).toBe(DEFAULT_PET_CONFIG);
  });
});

describe('read/write', () => {
  it('round-trips through disk and falls back on missing files', () => {
    const dir = mkdtempSync(join(tmpdir(), 'sage-pet-config-'));
    const file = join(dir, 'pet-config.json');
    try {
      expect(readPetConfig(file)).toEqual(DEFAULT_PET_CONFIG);
      const changed = mergePetConfig(DEFAULT_PET_CONFIG, {
        enabled: true,
        pets: [
          { id: 'default', petPack: 'dafeiyu', size: 'small' },
          { id: 'pet-2', petPack: 'custom', size: 'large' },
        ],
      });
      expect(writePetConfig(file, changed)).toBe(true);
      expect(readPetConfig(file)).toEqual(changed);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
