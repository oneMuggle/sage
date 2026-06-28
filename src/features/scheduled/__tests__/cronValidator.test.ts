import { describe, expect, it } from 'vitest';

import {
  validateCronExpression,
  validateOneShotTimestamp,
  describeSchedule,
  CRON_PRESETS,
} from '../cronValidator';

describe('validateCronExpression', () => {
  it('accepts a valid 5-field cron', () => {
    expect(validateCronExpression('0 8 * * *')).toEqual({ ok: true });
  });

  it('accepts step expressions', () => {
    expect(validateCronExpression('*/15 * * * *')).toEqual({ ok: true });
  });

  it('accepts every preset', () => {
    for (const preset of CRON_PRESETS) {
      const result = validateCronExpression(preset.cron);
      expect(result.ok, `preset ${preset.id} (${preset.cron}) should validate`).toBe(true);
    }
  });

  it('rejects empty string', () => {
    const result = validateCronExpression('');
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/empty/i);
  });

  it('rejects garbage input', () => {
    const result = validateCronExpression('not a cron');
    expect(result.ok).toBe(false);
  });

  it('rejects 6-field expressions (we only support 5-field)', () => {
    const result = validateCronExpression('0 0 8 * * *');
    expect(result.ok).toBe(false);
  });

  it('rejects out-of-range values', () => {
    expect(validateCronExpression('0 25 * * *').ok).toBe(false);
    expect(validateCronExpression('60 * * * *').ok).toBe(false);
  });

  it('trims whitespace before validating', () => {
    expect(validateCronExpression('   0 8 * * *   ').ok).toBe(true);
  });
});

describe('validateOneShotTimestamp', () => {
  it('accepts a future timestamp', () => {
    const future = Date.now() + 60_000;
    expect(validateOneShotTimestamp(future).ok).toBe(true);
  });

  it('rejects a past timestamp', () => {
    const past = Date.now() - 60_000;
    const result = validateOneShotTimestamp(past);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/future|past/i);
  });

  it('rejects non-finite values', () => {
    expect(validateOneShotTimestamp(Number.NaN).ok).toBe(false);
    expect(validateOneShotTimestamp(Number.POSITIVE_INFINITY).ok).toBe(false);
  });
});

describe('describeSchedule', () => {
  it('describes a recurring cron in user-friendly terms', () => {
    const text = describeSchedule({ kind: 'recurring', cron: '0 8 * * *' }, 'zh');
    expect(text).toMatch(/8|每天/);
  });

  it('describes a one-shot timestamp via Intl.DateTimeFormat', () => {
    const fixed = Date.UTC(2026, 5, 25, 8, 0, 0);
    const text = describeSchedule({ kind: 'once', at: fixed }, 'zh');
    expect(text.length).toBeGreaterThan(0);
  });

  it('returns Invalid cron placeholder for malformed expressions', () => {
    const text = describeSchedule({ kind: 'recurring', cron: 'garbage' }, 'en');
    expect(text.toLowerCase()).toMatch(/invalid|无效/);
  });
});
