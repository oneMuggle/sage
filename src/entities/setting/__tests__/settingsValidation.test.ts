import { describe, expect, it } from 'vitest';

import {
  formatSettingValidationJson,
  formatSettingValidationSummary,
  validateSettingValue,
} from '../settingsValidation';

describe('settingsValidation', () => {
  it('returns error for unknown setting keys', () => {
    expect(validateSettingValue('nonexistent.key', 123)).toBe('未知设置项: nonexistent.key');
  });

  it('formats setting validation summary and JSON (Phase P120)', () => {
    expect(formatSettingValidationSummary('nonexistent.key', 123)).toBe(
      'nonexistent.key · invalid(未知设置项: nonexistent.key)',
    );
    expect(JSON.parse(formatSettingValidationJson('nonexistent.key', 123))).toEqual({
      key: 'nonexistent.key',
      valid: false,
      error: '未知设置项: nonexistent.key',
    });
  });
});
