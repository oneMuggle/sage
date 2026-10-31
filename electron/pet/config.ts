/**
 * Pet configuration — single owner is the Electron main process.
 *
 * Stored at `<userData>/pet-config.json`; intentionally outside AppSettings
 * so the backend settings canonicalizer / Win7 parity tests do not change.
 *
 * v2 (2026-10-31): multiple pets. Each instance carries its own pack/size;
 * behavior settings (tempo/bubble/sound/...) stay global. v1 files migrate
 * to a single `default` pet on read.
 */

import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

import type {
  PetBubbleMode,
  PetCompatibilityMode,
  PetConfig,
  PetDisplayMode,
  PetInstanceConfig,
  PetSize,
  PetTempo,
} from './types';

export const MAX_PETS = 3;

export const DEFAULT_PET_CONFIG: PetConfig = {
  version: 2,
  enabled: false,
  displayMode: 'desktop',
  tempo: 'standard',
  reduceMotion: false,
  bubbleMode: 'important',
  soundScenes: { waiting: true, error: false, done: false },
  showSessionTitle: false,
  compatibilityMode: 'auto',
  followActiveSession: true,
<<<<<<< HEAD
=======
  externalApi: false,
>>>>>>> origin/main
  pets: [{ id: 'default', petPack: 'dafeiyu', size: 'medium' }],
};

const DISPLAY_MODES: PetDisplayMode[] = ['desktop', 'in-app', 'both', 'off'];
const SIZES: PetSize[] = ['mini', 'small', 'medium', 'large', 'huge'];
const TEMPOS: PetTempo[] = ['quiet', 'standard', 'lively'];
const BUBBLE_MODES: PetBubbleMode[] = ['important', 'always', 'off'];
const COMPATIBILITY_MODES: PetCompatibilityMode[] = ['auto', 'on', 'off'];
const PET_ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,31}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function pick<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === 'string' && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : fallback;
}

function pickBool(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

function text(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function nextPetId(used: Set<string>): string {
  for (let i = 1; i <= MAX_PETS + 10; i++) {
    const candidate = `pet-${i}`;
    if (!used.has(candidate)) return candidate;
  }
  return `pet-${Date.now().toString(36)}`;
}

/**
 * Normalize the `pets` array (v2) or synthesize one pet from v1 top-level
 * `petPack`/`size`. Invalid/duplicate ids are replaced; the list is capped.
 */
function normalizePets(source: Record<string, unknown>): PetInstanceConfig[] {
  const legacyPack = text(source.petPack) ?? DEFAULT_PET_CONFIG.pets[0]!.petPack;
  const legacySize = pick(source.size, SIZES, DEFAULT_PET_CONFIG.pets[0]!.size);
  const rawPets = Array.isArray(source.pets) ? source.pets : null;
  const candidates = rawPets ?? [{ id: 'default', petPack: legacyPack, size: legacySize }];
  const used = new Set<string>();
  const pets: PetInstanceConfig[] = [];
  for (const raw of candidates) {
    if (pets.length >= MAX_PETS) break;
    if (!isRecord(raw)) continue;
    const pack = text(raw.petPack) ?? legacyPack;
    const size = pick(raw.size, SIZES, legacySize);
    const claimed = text(raw.id)?.toLowerCase() ?? '';
    const id = PET_ID_PATTERN.test(claimed) && !used.has(claimed) ? claimed : nextPetId(used);
    used.add(id);
    pets.push({ id, petPack: pack, size });
  }
  if (pets.length === 0) {
    pets.push({ id: 'default', petPack: legacyPack, size: legacySize });
  }
  return pets;
}

export function normalizePetConfig(raw: unknown): PetConfig {
  const source = isRecord(raw) ? raw : {};
  const scenes = isRecord(source.soundScenes) ? source.soundScenes : {};
  return {
    version: 2,
    enabled: pickBool(source.enabled, DEFAULT_PET_CONFIG.enabled),
    displayMode: pick(source.displayMode, DISPLAY_MODES, DEFAULT_PET_CONFIG.displayMode),
    tempo: pick(source.tempo, TEMPOS, DEFAULT_PET_CONFIG.tempo),
    reduceMotion: pickBool(source.reduceMotion, DEFAULT_PET_CONFIG.reduceMotion),
    bubbleMode: pick(source.bubbleMode, BUBBLE_MODES, DEFAULT_PET_CONFIG.bubbleMode),
    soundScenes: {
      waiting: pickBool(scenes.waiting, DEFAULT_PET_CONFIG.soundScenes.waiting),
      error: pickBool(scenes.error, DEFAULT_PET_CONFIG.soundScenes.error),
      done: pickBool(scenes.done, DEFAULT_PET_CONFIG.soundScenes.done),
    },
    showSessionTitle: pickBool(source.showSessionTitle, DEFAULT_PET_CONFIG.showSessionTitle),
    compatibilityMode: pick(
      source.compatibilityMode,
      COMPATIBILITY_MODES,
      DEFAULT_PET_CONFIG.compatibilityMode,
    ),
    followActiveSession: pickBool(
      source.followActiveSession,
      DEFAULT_PET_CONFIG.followActiveSession,
    ),
<<<<<<< HEAD
=======
    externalApi: pickBool(source.externalApi, DEFAULT_PET_CONFIG.externalApi),
>>>>>>> origin/main
    pets: normalizePets(source),
  };
}

export function mergePetConfig(current: PetConfig, patch: unknown): PetConfig {
  if (!isRecord(patch)) return current;
  const merged: Record<string, unknown> = { ...current, ...patch };
  if (isRecord(patch.soundScenes)) {
    merged.soundScenes = { ...current.soundScenes, ...patch.soundScenes };
  }
  // Legacy single-pet patches (import/delete/tray type of callers) apply to
  // the first pet; new callers should patch the whole `pets` array instead.
  if (!Array.isArray(patch.pets) && (patch.petPack !== undefined || patch.size !== undefined)) {
    const [first, ...rest] = current.pets;
    merged.pets = [
      {
        ...first,
        ...(typeof patch.petPack === 'string' ? { petPack: patch.petPack } : {}),
        ...(typeof patch.size === 'string' ? { size: patch.size } : {}),
      },
      ...rest,
    ];
    delete merged.petPack;
    delete merged.size;
  }
  return normalizePetConfig(merged);
}

export function readPetConfig(file: string): PetConfig {
  try {
    if (!existsSync(file)) return DEFAULT_PET_CONFIG;
    const parsed: unknown = JSON.parse(readFileSync(file, 'utf8'));
    return normalizePetConfig(parsed);
  } catch {
    return DEFAULT_PET_CONFIG;
  }
}

export function writePetConfig(file: string, config: PetConfig): boolean {
  try {
    mkdirSync(dirname(file), { recursive: true });
    const temporary = `${file}.tmp`;
    writeFileSync(temporary, `${JSON.stringify(config, null, 2)}\n`, 'utf8');
    renameSync(temporary, file);
    return true;
  } catch {
    return false;
  }
}
