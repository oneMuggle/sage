/**
 * Pet configuration — single owner is the Electron main process.
 *
 * Stored at `<userData>/pet-config.json`; intentionally outside AppSettings
 * so the backend settings canonicalizer / Win7 parity tests do not change.
 */

import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

import type {
  PetBubbleMode,
  PetCompatibilityMode,
  PetConfig,
  PetDisplayMode,
  PetSize,
  PetTempo,
} from './types';

export const DEFAULT_PET_CONFIG: PetConfig = {
  version: 1,
  enabled: false,
  displayMode: 'desktop',
  size: 'medium',
  tempo: 'standard',
  reduceMotion: false,
  bubbleMode: 'important',
  soundScenes: { waiting: true, error: false, done: false },
  showSessionTitle: false,
  compatibilityMode: 'auto',
  petPack: 'dafeiyu',
  followActiveSession: true,
};

const DISPLAY_MODES: PetDisplayMode[] = ['desktop', 'in-app', 'both', 'off'];
const SIZES: PetSize[] = ['mini', 'small', 'medium', 'large', 'huge'];
const TEMPOS: PetTempo[] = ['quiet', 'standard', 'lively'];
const BUBBLE_MODES: PetBubbleMode[] = ['important', 'always', 'off'];
const COMPATIBILITY_MODES: PetCompatibilityMode[] = ['auto', 'on', 'off'];

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

export function normalizePetConfig(raw: unknown): PetConfig {
  const source = isRecord(raw) ? raw : {};
  const scenes = isRecord(source.soundScenes) ? source.soundScenes : {};
  const pack =
    typeof source.petPack === 'string' && source.petPack.trim()
      ? source.petPack.trim()
      : DEFAULT_PET_CONFIG.petPack;
  return {
    version: 1,
    enabled: pickBool(source.enabled, DEFAULT_PET_CONFIG.enabled),
    displayMode: pick(source.displayMode, DISPLAY_MODES, DEFAULT_PET_CONFIG.displayMode),
    size: pick(source.size, SIZES, DEFAULT_PET_CONFIG.size),
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
    petPack: pack,
    followActiveSession: pickBool(
      source.followActiveSession,
      DEFAULT_PET_CONFIG.followActiveSession,
    ),
  };
}

export function mergePetConfig(current: PetConfig, patch: unknown): PetConfig {
  if (!isRecord(patch)) return current;
  const merged: Record<string, unknown> = { ...current, ...patch };
  if (isRecord(patch.soundScenes)) {
    merged.soundScenes = { ...current.soundScenes, ...patch.soundScenes };
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
