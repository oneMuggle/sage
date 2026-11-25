/**
 * healthSeverity SEVERITY_TOKENS 回归测试
 *
 * 锁住缺陷 #4 的修复：critical/warning/ok 必须使用项目语义色 token
 *（error / warning / success），不得回退到原始 Tailwind 调色板（rose / amber / emerald / orange）。
 */
import { describe, expect, it } from 'vitest';

import { SEVERITY_ORDER, SEVERITY_TOKENS, type SeverityToken } from '../healthSeverity';

const RAW_PALETTE = ['rose', 'amber', 'emerald', 'orange', 'red', 'green', 'yellow'];
const SEMANTIC_KEYS = {
  critical: 'error',
  warning: 'warning',
  ok: 'success',
} as const;

const REQUIRED_FIELDS: (keyof SeverityToken)[] = [
  'label',
  'stateLabel',
  'Icon',
  'dot',
  'text',
  'softBg',
  'border',
  'badge',
];

describe('SEVERITY_TOKENS uses semantic color tokens', () => {
  it('has the full set of severity levels in SEVERITY_ORDER', () => {
    expect([...SEVERITY_ORDER].sort()).toEqual(['critical', 'ok', 'warning']);
  });

  for (const severity of SEVERITY_ORDER) {
    describe(`severity = ${severity}`, () => {
      const token = SEVERITY_TOKENS[severity];

      it('defines all required fields with non-empty strings (Icon is a component)', () => {
        expect(token.Icon).toBeDefined();
        const stringFields = REQUIRED_FIELDS.filter((f) => f !== 'Icon');
        for (const field of stringFields) {
          const value = token[field];
          expect(typeof value).toBe('string');
          expect(value).not.toBe('');
        }
      });

      it(`contains no raw Tailwind palette class`, () => {
        const joined = [token.dot, token.text, token.softBg, token.border, token.badge].join(' ');
        for (const raw of RAW_PALETTE) {
          expect(joined).not.toContain(`${raw}-`);
          expect(joined).not.toContain(`${raw}/`);
        }
      });

      it(`uses the expected semantic color "${SEMANTIC_KEYS[severity]}"`, () => {
        const semantic = SEMANTIC_KEYS[severity];
        const joined = [token.dot, token.text, token.softBg, token.border, token.badge].join(' ');
        expect(joined).toContain(semantic);
      });
    });
  }
});
