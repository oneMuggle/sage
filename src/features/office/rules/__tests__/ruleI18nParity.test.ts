// src/features/office/rules/__tests__/ruleI18nParity.test.ts
import { describe, expect, it } from 'vitest';

import { en } from '../../../../shared/lib/i18n/en';
import { zh } from '../../../../shared/lib/i18n/zh';
import { RULE_CHECK_MODES, RULE_SCOPES, RULE_SEVERITIES, RULE_TYPES } from '../ruleTypes';

const RULES_PREFIX = 'office.rules.';

function rulesKeys(table: object): string[] {
  return Object.keys(table)
    .filter((key) => key.startsWith(RULES_PREFIX))
    .sort();
}

// These four families are built with template literals at the call site
// (`t(\`office.rules.severity.${severity}\`)`), so a missing value would only
// surface as a raw key on screen.
const DYNAMIC_KEYS = [
  ...RULE_TYPES.map((value) => `office.rules.type.${value}`),
  ...RULE_SEVERITIES.map((value) => `office.rules.severity.${value}`),
  ...RULE_SCOPES.map((value) => `office.rules.scope.${value}`),
  ...RULE_CHECK_MODES.map((value) => `office.rules.checkMode.${value}`),
];

describe('office rules i18n parity', () => {
  it('defines at least one rules key', () => {
    expect(rulesKeys(zh).length).toBeGreaterThan(0);
  });

  it('exposes the same office.rules.* key set in zh and en', () => {
    expect(rulesKeys(en)).toEqual(rulesKeys(zh));
  });

  it.each(DYNAMIC_KEYS)('%s is non-empty in both locales', (key) => {
    expect(zh[key as keyof typeof zh]).toBeTruthy();
    expect(en[key as keyof typeof en]).toBeTruthy();
  });

  it('has every rules key non-empty in both locales', () => {
    for (const key of rulesKeys(zh)) {
      expect(zh[key as keyof typeof zh], `${key} (zh)`).toBeTruthy();
      expect(en[key as keyof typeof en], `${key} (en)`).toBeTruthy();
    }
  });
});
