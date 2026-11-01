import { describe, expect, it } from 'vitest';

import { zhPlaybook } from '../../zh/playbook';
import { enPlaybook } from '../playbook';

function placeholders(value: string): string[] {
  return Array.from(value.matchAll(/\{(\w+)\}/g), (match) => match[1]).sort();
}

describe('playbook locale dictionary', () => {
  it('en and zh expose the same keys with non-empty values', () => {
    const zhKeys = Object.keys(zhPlaybook).sort();
    const enKeys = Object.keys(enPlaybook).sort();
    expect(enKeys).toEqual(zhKeys);
    for (const key of zhKeys) {
      expect(zhPlaybook[key as keyof typeof zhPlaybook].trim().length).toBeGreaterThan(0);
      expect(enPlaybook[key as keyof typeof enPlaybook].trim().length).toBeGreaterThan(0);
    }
  });

  it('both locales use the same interpolation placeholders', () => {
    for (const key of Object.keys(zhPlaybook) as Array<keyof typeof zhPlaybook>) {
      expect(placeholders(enPlaybook[key])).toEqual(placeholders(zhPlaybook[key]));
    }
  });
});
