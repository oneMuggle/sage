import { mkdirSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { detectProjectRoot } from '../projectDetector';

describe('detectProjectRoot', () => {
  let testDir: string;

  beforeEach(() => {
    testDir = join(
      tmpdir(),
      `sage-project-detector-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    );
    mkdirSync(testDir, { recursive: true });
  });

  afterEach(() => {
    rmSync(testDir, { recursive: true, force: true });
  });

  it('returns the directory containing .git', () => {
    mkdirSync(join(testDir, 'a', 'b', 'c'), { recursive: true });
    mkdirSync(join(testDir, 'a', '.git'));
    expect(detectProjectRoot(join(testDir, 'a', 'b', 'c'))).toBe(join(testDir, 'a'));
  });

  it('returns the directory containing package.json', () => {
    mkdirSync(join(testDir, 'proj'), { recursive: true });
    writeFileSync(join(testDir, 'proj', 'package.json'), '{}');
    expect(detectProjectRoot(join(testDir, 'proj'))).toBe(join(testDir, 'proj'));
  });

  it('returns the directory containing pyproject.toml', () => {
    mkdirSync(join(testDir, 'proj'), { recursive: true });
    writeFileSync(join(testDir, 'proj', 'pyproject.toml'), '');
    expect(detectProjectRoot(join(testDir, 'proj'))).toBe(join(testDir, 'proj'));
  });

  it('returns the directory containing Cargo.toml', () => {
    mkdirSync(join(testDir, 'proj'), { recursive: true });
    writeFileSync(join(testDir, 'proj', 'Cargo.toml'), '');
    expect(detectProjectRoot(join(testDir, 'proj'))).toBe(join(testDir, 'proj'));
  });

  it('returns the directory containing go.mod', () => {
    mkdirSync(join(testDir, 'proj'), { recursive: true });
    writeFileSync(join(testDir, 'proj', 'go.mod'), '');
    expect(detectProjectRoot(join(testDir, 'proj'))).toBe(join(testDir, 'proj'));
  });

  it('returns null when no marker exists within max depth', () => {
    // Create a deep directory with no markers
    const deep = join(testDir, 'a', 'b', 'c', 'd', 'e', 'f');
    mkdirSync(deep, { recursive: true });
    expect(detectProjectRoot(deep)).toBeNull();
  });

  it('stops at max depth (5 levels up)', () => {
    // Marker is 6 levels up — beyond MAX_DEPTH=5
    const nested = join(testDir, 'a', 'b', 'c', 'd', 'e', 'f');
    mkdirSync(nested, { recursive: true });
    writeFileSync(join(testDir, 'package.json'), '{}'); // at testDir level
    // testDir is 6 levels above nested: a/b/c/d/e/f → testDir
    // detectProjectRoot walks 0..5 = 6 levels, so testDir is at depth 6 → not found
    expect(detectProjectRoot(nested)).toBeNull();
  });

  it('finds marker within max depth', () => {
    // Marker is 3 levels up — within MAX_DEPTH=5
    const nested = join(testDir, 'a', 'b', 'c');
    mkdirSync(nested, { recursive: true });
    writeFileSync(join(testDir, 'package.json'), '{}'); // 3 levels up
    expect(detectProjectRoot(nested)).toBe(testDir);
  });

  it('returns the start directory when it is itself a project root', () => {
    writeFileSync(join(testDir, '.git'), '');
    expect(detectProjectRoot(testDir)).toBe(testDir);
  });
});
