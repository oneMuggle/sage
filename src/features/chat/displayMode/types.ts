export type DisplayMode = 'detail' | 'trace' | 'result';

export const DEFAULT_DISPLAY_MODE: DisplayMode = 'trace';

export const DISPLAY_MODE_VALUES: readonly DisplayMode[] = ['detail', 'trace', 'result'];

export function isValidDisplayMode(value: unknown): value is DisplayMode {
  return (
    typeof value === 'string' &&
    (value === 'detail' || value === 'trace' || value === 'result')
  );
}
