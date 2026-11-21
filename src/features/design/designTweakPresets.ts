/**
 * Design tweak presets — localStorage-backed named tweak sets.
 */
import type { ProjectTweaks } from '../../entities/design/types';

export interface TweakPreset {
  name: string;
  tweaks: ProjectTweaks;
}

const STORAGE_KEY = 'sage.design.tweakPresets';

function readStorage(): TweakPreset[] {
  if (typeof window === 'undefined' || !window.localStorage) return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item): item is TweakPreset =>
        typeof item === 'object' &&
        item !== null &&
        typeof (item as TweakPreset).name === 'string' &&
        typeof (item as TweakPreset).tweaks === 'object' &&
        (item as TweakPreset).tweaks !== null,
    );
  } catch {
    return [];
  }
}

function writeStorage(presets: TweakPreset[]): void {
  if (typeof window === 'undefined' || !window.localStorage) return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(presets));
}

/** List saved presets, newest first. */
export function loadPresets(): TweakPreset[] {
  return readStorage();
}

/** Save (or overwrite by name) a preset holding the non-null tweak fields. */
export function savePreset(name: string, tweaks: ProjectTweaks): TweakPreset[] {
  const trimmed = name.trim();
  if (!trimmed) return readStorage();
  const compact = Object.fromEntries(
    Object.entries(tweaks).filter(([, value]) => value !== null && value !== undefined),
  ) as ProjectTweaks;
  const next = [
    { name: trimmed, tweaks: compact },
    ...readStorage().filter((preset) => preset.name !== trimmed),
  ];
  writeStorage(next);
  return next;
}

/** Remove a preset by name. */
export function deletePreset(name: string): TweakPreset[] {
  const next = readStorage().filter((preset) => preset.name !== name);
  writeStorage(next);
  return next;
}
