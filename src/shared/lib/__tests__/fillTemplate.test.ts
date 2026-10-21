import { describe, expect, it } from 'vitest';

import {
  fillTemplate,
  formatFillTemplateSummary,
  formatFillTemplateJson,
} from '../fillTemplate';

describe('fillTemplate audit helpers', () => {
  it('fills template placeholders and formats summary and json', () => {
    expect(fillTemplate('Hello {name}, count={n} ({missing})', { name: 'Sage', n: 3 })).toBe(
      'Hello Sage, count=3 ({missing})',
    );
    expect(
      formatFillTemplateSummary('Hello {name}, count={n} ({missing})', { name: 'Sage', n: 3 }),
    ).toBe('placeholders=3 · filled=2 · unresolved=1');
    const parsed = JSON.parse(
      formatFillTemplateJson('Hello {name}', { name: 'Sage' }),
    );
    expect(parsed).toEqual({
      placeholders: 1,
      filled: 1,
      unresolved: 0,
      result: 'Hello Sage',
    });
  });

  it('handles nullish template or vars safely', () => {
    expect(formatFillTemplateSummary(null, null)).toBe(
      'placeholders=0 · filled=0 · unresolved=0',
    );
    expect(JSON.parse(formatFillTemplateJson(undefined, undefined)).result).toBe('');
  });
});
