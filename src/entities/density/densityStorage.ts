import {
  DENSITY_DEFAULT,
  DENSITY_STORAGE_KEY,
  normalizeDensityMode,
  type DensityMode,
} from './densityMode';

export function loadDensity(): DensityMode {
  try {
    const raw = localStorage.getItem(DENSITY_STORAGE_KEY);
    return normalizeDensityMode(raw);
  } catch {
    return DENSITY_DEFAULT;
  }
}

export function saveDensity(mode: DensityMode): void {
  try {
    localStorage.setItem(DENSITY_STORAGE_KEY, mode);
  } catch {
    // localStorage unavailable (private mode / quota exceeded) — silently ignore.
  }
}
