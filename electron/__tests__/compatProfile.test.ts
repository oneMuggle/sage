/**
 * compatProfile — 兼容档位纯逻辑镜像（与 Python backend.services.rescue.compat_profile 同步）。
 */
import { describe, expect, it } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

import {
  CURRENT_SCHEMA,
  LEVEL_APP_FEATURES,
  LEVEL_FLAGS,
  bumpLevel,
  effectiveAppFeatures,
  effectiveFlags,
  newProfile,
  readCompatProfile,
  writeCompatProfile,
} from '../compatProfile';

describe('compatProfile pure logic', () => {
  it('L0 disables no extra flags', () => {
    const p = newProfile(0, 'default', '2026-11-08T10:00:00Z');
    expect(p.schema).toBe(CURRENT_SCHEMA);
    expect(p.level).toBe(0);
    expect(effectiveFlags(p)).toEqual([]);
    expect(effectiveAppFeatures(p).petWindow).toBe(true);
  });

  it('L1 disables pet + preview and adds compositing flags', () => {
    const p = newProfile(1, 'crash', '2026-11-08T10:00:00Z');
    expect(effectiveFlags(p)).toContain('disable-gpu-compositing');
    expect(effectiveAppFeatures(p).petWindow).toBe(false);
    expect(effectiveAppFeatures(p).previewHost).toBe(false);
    expect(effectiveAppFeatures(p).browserBridge).toBe(true);
  });

  it('L3 adds single-process and disables browser bridge/update check', () => {
    const p = newProfile(3, 'experimental', '2026-11-08T10:00:00Z');
    expect(effectiveFlags(p)).toContain('single-process');
    expect(effectiveAppFeatures(p).browserBridge).toBe(false);
    expect(effectiveAppFeatures(p).updateCheck).toBe(false);
  });

  it('bumpLevel caps at 3', () => {
    const p = newProfile(2, 'x', '2026-11-08T10:00:00Z');
    const b = bumpLevel(p, 'crash', '2026-11-08T10:01:00Z');
    expect(b.level).toBe(3);
    expect(bumpLevel(b, 'crash', '2026-11-08T10:02:00Z').level).toBe(3);
  });

  it('rejects out-of-range level', () => {
    expect(() => newProfile(4, 'x', '2026-11-08T10:00:00Z')).toThrow();
  });

  it('readCompatProfile returns default on missing file', () => {
    const dir = mkdtempSync(join(tmpdir(), 'sage-compat-'));
    try {
      const p = readCompatProfile(join(dir, 'compat.json'));
      expect(p.level).toBe(0);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it('readCompatProfile returns default on invalid schema', () => {
    const dir = mkdtempSync(join(tmpdir(), 'sage-compat-'));
    const file = join(dir, 'compat.json');
    try {
      writeFileSync(file, JSON.stringify({ schema: 999, level: 2 }), 'utf-8');
      expect(readCompatProfile(file).level).toBe(0);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it('readCompatProfile returns default on fractional level', () => {
    const dir = mkdtempSync(join(tmpdir(), 'sage-compat-'));
    const file = join(dir, 'compat.json');
    try {
      writeFileSync(file, JSON.stringify({ schema: 1, level: 1.5 }), 'utf-8');
      expect(readCompatProfile(file).level).toBe(0);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it('write + read roundtrip', () => {
    const dir = mkdtempSync(join(tmpdir(), 'sage-compat-'));
    const file = join(dir, 'nested', 'compat.json');
    try {
      const p = newProfile(2, 'test', '2026-11-08T10:00:00Z');
      writeCompatProfile(file, p);
      expect(readCompatProfile(file).level).toBe(2);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it('LEVEL tables have identical key sets', () => {
    expect(Object.keys(LEVEL_FLAGS).sort()).toEqual(Object.keys(LEVEL_APP_FEATURES).sort());
  });
});
