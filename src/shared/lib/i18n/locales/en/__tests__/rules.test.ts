import { describe, expect, it } from 'vitest';

import { zhRules } from '../../zh/rules';
import { enRules } from '../rules';

function placeholders(value: string): string[] {
  return Array.from(value.matchAll(/\{(\w+)\}/g), (match) => match[1]).sort();
}

describe('rules locale dictionary', () => {
  it('en and zh expose the same keys with non-empty values', () => {
    const zhKeys = Object.keys(zhRules).sort();
    expect(Object.keys(enRules).sort()).toEqual(zhKeys);
    for (const key of zhKeys) {
      expect(zhRules[key as keyof typeof zhRules].trim().length).toBeGreaterThan(0);
      expect(enRules[key as keyof typeof enRules].trim().length).toBeGreaterThan(0);
    }
  });

  it('both locales use the same interpolation placeholders', () => {
    for (const key of Object.keys(zhRules) as Array<keyof typeof zhRules>) {
      expect(placeholders(enRules[key])).toEqual(placeholders(zhRules[key]));
    }
  });
});
