/**
 * Pet companion profile — pat count and relationship start.
 *
 * Kept separate from pet-config.json so config resets do not wipe the bond.
 */

import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

export interface PetProfile {
  version: 1;
  firstSeenAt: number | null;
  patCount: number;
  lastPatAt: number | null;
}

const DAY_MS = 24 * 60 * 60 * 1000;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function positive(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return null;
  return value;
}

export function normalizePetProfile(raw: unknown, now: number): PetProfile {
  const source = isRecord(raw) ? raw : {};
  const firstSeenAt = positive(source.firstSeenAt) ?? now;
  const patCount =
    typeof source.patCount === 'number' && Number.isFinite(source.patCount) && source.patCount >= 0
      ? Math.floor(source.patCount)
      : 0;
  return {
    version: 1,
    firstSeenAt,
    patCount,
    lastPatAt: positive(source.lastPatAt),
  };
}

export function readPetProfile(file: string, now: number): PetProfile {
  try {
    if (!existsSync(file)) return normalizePetProfile(null, now);
    return normalizePetProfile(JSON.parse(readFileSync(file, 'utf8')), now);
  } catch {
    return normalizePetProfile(null, now);
  }
}

export function writePetProfile(file: string, profile: PetProfile): boolean {
  try {
    mkdirSync(dirname(file), { recursive: true });
    const temporary = `${file}.tmp`;
    writeFileSync(temporary, `${JSON.stringify(profile, null, 2)}\n`, 'utf8');
    renameSync(temporary, file);
    return true;
  } catch {
    return false;
  }
}

export function recordPat(profile: PetProfile, now: number): PetProfile {
  return {
    ...profile,
    patCount: profile.patCount + 1,
    lastPatAt: now,
  };
}

export function bondDays(profile: PetProfile, now: number): number {
  if (!profile.firstSeenAt) return 1;
  return Math.max(1, Math.floor((now - profile.firstSeenAt) / DAY_MS) + 1);
}
