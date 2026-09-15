export type FontFamilyId =
  | 'inter'
  | 'system'
  | 'noto-sans-sc'
  | 'pingfang'
  | 'jetbrains-mono'
  | 'fira-code'
  | 'source-code-pro'
  | 'consolas'
  | 'monaco';

export interface FontOption {
  readonly id: FontFamilyId;
  readonly label: string;
  readonly stack: string;
}

export interface FontSettings {
  fontUi: FontFamilyId;
  fontCode: FontFamilyId;
  fontSizeUi: number;
  fontSizeCode: number;
}

export const UI_FONT_OPTIONS: readonly FontOption[] = [
  {
    id: 'inter',
    label: 'Inter',
    stack: 'Inter, "Noto Sans SC", system-ui, -apple-system, sans-serif',
  },
  { id: 'system', label: '系统默认', stack: 'system-ui, -apple-system, "Segoe UI", sans-serif' },
  {
    id: 'noto-sans-sc',
    label: '思源黑体',
    stack: '"Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif',
  },
  { id: 'pingfang', label: '苹方', stack: '"PingFang SC", "Noto Sans SC", sans-serif' },
];

export const CODE_FONT_OPTIONS: readonly FontOption[] = [
  { id: 'jetbrains-mono', label: 'JetBrains Mono', stack: '"JetBrains Mono", monospace' },
  { id: 'fira-code', label: 'Fira Code', stack: '"Fira Code", monospace' },
  { id: 'source-code-pro', label: 'Source Code Pro', stack: '"Source Code Pro", monospace' },
  { id: 'consolas', label: 'Consolas', stack: 'Consolas, "Courier New", monospace' },
  { id: 'monaco', label: 'Monaco', stack: 'Monaco, monospace' },
];

export const FONT_DEFAULTS: Readonly<FontSettings> = {
  fontUi: 'inter',
  fontCode: 'jetbrains-mono',
  fontSizeUi: 14,
  fontSizeCode: 13,
};

export const FONT_SIZE_MIN = 10;
export const FONT_SIZE_MAX = 24;

export function normalizeFontSize(value: unknown, fallback: number): number {
  if (typeof value !== 'number' && typeof value !== 'string') return fallback;
  if (typeof value === 'string' && value.trim() === '') return fallback;
  const size = Number(value);
  if (!Number.isFinite(size)) return fallback;
  return Math.min(FONT_SIZE_MAX, Math.max(FONT_SIZE_MIN, Math.floor(size)));
}

function normalizeFamily(
  value: unknown,
  options: readonly FontOption[],
  fallback: FontFamilyId,
): FontFamilyId {
  return options.find((option) => option.id === value)?.id ?? fallback;
}

export function normalizeFontSettings(value: unknown): FontSettings {
  const settings =
    value !== null && typeof value === 'object' && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  return {
    fontUi: normalizeFamily(settings.fontUi, UI_FONT_OPTIONS, FONT_DEFAULTS.fontUi),
    fontCode: normalizeFamily(settings.fontCode, CODE_FONT_OPTIONS, FONT_DEFAULTS.fontCode),
    fontSizeUi: normalizeFontSize(settings.fontSizeUi, FONT_DEFAULTS.fontSizeUi),
    fontSizeCode: normalizeFontSize(settings.fontSizeCode, FONT_DEFAULTS.fontSizeCode),
  };
}
