export type DensityMode = 'comfortable' | 'compact';

export const DENSITY_MODES: readonly DensityMode[] = ['comfortable', 'compact'] as const;

export const DENSITY_DEFAULT: DensityMode = 'comfortable';

export const DENSITY_STORAGE_KEY = 'sage-density-mode';

export const DENSITY_LABELS: Record<DensityMode, string> = {
  comfortable: '舒适',
  compact: '紧凑',
};

export function normalizeDensityMode(value: unknown): DensityMode {
  if (typeof value === 'string' && DENSITY_MODES.includes(value as DensityMode)) {
    return value as DensityMode;
  }
  return DENSITY_DEFAULT;
}
