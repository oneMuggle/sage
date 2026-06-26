// Cron expression validation and human-readable descriptions.
//
// No third-party deps — we re-implement the small subset of cron syntax
// we need. Supported format: 5-field standard cron
//   minute hour day-of-month month day-of-week
// with *, integer lists (1,15), ranges (1-5), and steps (*/15).
//
// Display layer uses Intl.DateTimeFormat for locale-aware formatting.

export type ValidationResult = { ok: true } | { ok: false; reason: string };

export interface CronPreset {
  id: string;
  labelKey: string; // i18n key for human label
  cron: string;
}

export const CRON_PRESETS: readonly CronPreset[] = [
  { id: 'hourly', labelKey: 'cron.preset.hourly', cron: '0 * * * *' },
  { id: 'daily-08', labelKey: 'cron.preset.daily08', cron: '0 8 * * *' },
  { id: 'daily-18', labelKey: 'cron.preset.daily18', cron: '0 18 * * *' },
  { id: 'weekday-09', labelKey: 'cron.preset.weekday09', cron: '0 9 * * 1-5' },
  { id: 'weekly-mon', labelKey: 'cron.preset.weeklyMon', cron: '0 9 * * 1' },
  { id: 'monthly-1st', labelKey: 'cron.preset.monthly1st', cron: '0 9 1 * *' },
];

const FIELD_RANGES = [
  { min: 0, max: 59 }, // minute
  { min: 0, max: 23 }, // hour
  { min: 1, max: 31 }, // day of month
  { min: 1, max: 12 }, // month
  { min: 0, max: 6 }, // day of week (0 = Sunday)
] as const;

function validateField(value: string, min: number, max: number): boolean {
  if (value === '*') return true;
  for (const part of value.split(',')) {
    let body = part;
    let step = 1;
    if (body.includes('/')) {
      const [base, stepStr] = body.split('/');
      const parsedStep = Number(stepStr);
      if (!Number.isInteger(parsedStep) || parsedStep < 1) return false;
      step = parsedStep;
      body = base === '' ? '*' : base;
    }
    if (body === '*') {
      if (step > max - min + 1) return false;
      continue;
    }
    if (body.includes('-')) {
      const [lo, hi] = body.split('-').map(Number);
      if (!Number.isInteger(lo) || !Number.isInteger(hi)) return false;
      if (lo < min || hi > max || lo > hi) return false;
      if (step > hi - lo + 1) return false;
      continue;
    }
    const num = Number(body);
    if (!Number.isInteger(num) || num < min || num > max) return false;
  }
  return true;
}

export function validateCronExpression(input: string): ValidationResult {
  const trimmed = (input ?? '').trim();
  if (trimmed === '') return { ok: false, reason: 'Cron expression must not be empty' };
  const parts = trimmed.split(/\s+/);
  if (parts.length !== 5) {
    return { ok: false, reason: `Expected 5 fields, got ${parts.length}` };
  }
  for (let i = 0; i < parts.length; i++) {
    if (!validateField(parts[i], FIELD_RANGES[i].min, FIELD_RANGES[i].max)) {
      return { ok: false, reason: `Field ${i + 1} is out of range or malformed` };
    }
  }
  return { ok: true };
}

export function validateOneShotTimestamp(atMs: number): ValidationResult {
  if (!Number.isFinite(atMs) || atMs === Number.POSITIVE_INFINITY) {
    return { ok: false, reason: 'Timestamp must be a finite number' };
  }
  if (atMs <= Date.now()) {
    return { ok: false, reason: 'One-shot time must be in the future' };
  }
  return { ok: true };
}

const ZH_LOCALE = 'zh-CN';

function formatDateTime(ms: number, locale: 'zh' | 'en'): string {
  const intlLocale = locale === 'zh' ? ZH_LOCALE : 'en-US';
  return new Intl.DateTimeFormat(intlLocale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(ms));
}

export function describeSchedule(
  schedule: { kind: 'once'; at: number } | { kind: 'recurring'; cron: string },
  locale: 'zh' | 'en' = 'zh',
): string {
  if (schedule.kind === 'once') {
    return formatDateTime(schedule.at, locale);
  }
  const validation = validateCronExpression(schedule.cron);
  if (!validation.ok) {
    return locale === 'zh' ? '无效的 Cron 表达式' : 'Invalid cron expression';
  }
  const preset = CRON_PRESETS.find((p) => p.cron === schedule.cron);
  if (preset) {
    return `[${preset.id}] ${schedule.cron}`;
  }
  return `cron: ${schedule.cron}`;
}
