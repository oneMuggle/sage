import { describe, expect, it } from 'vitest';

import { ALLOWED_CSS_VARS } from '../../../types/theme';
import {
  MAX_LINE_LENGTH,
  MAX_TOTAL_LENGTH,
  parseVars,
  validateCss,
} from '../cssValidator';

// --- 16-var whitelist: each var must be allowed ---

describe('ALLOWED_CSS_VARS', () => {
  for (const varName of ALLOWED_CSS_VARS) {
    it(`accepts valid value for ${varName}`, () => {
      const css = `:root { ${varName}: #fff; }`;
      const result = validateCss(css);
      expect(result.valid).toBe(true);
    });
  }
});

describe('parseVars', () => {
  it('extracts a single var', () => {
    expect(parseVars(':root { --color-bg: #fff; }')).toEqual({ '--color-bg': '#fff' });
  });
  it('extracts multiple vars', () => {
    const css = ':root { --color-bg: #fff; --color-fg: #000; }';
    expect(parseVars(css)).toEqual({ '--color-bg': '#fff', '--color-fg': '#000' });
  });
  it('returns empty for non-:root input', () => {
    expect(parseVars('body { --color-bg: red; }')).toEqual({});
  });
  it('returns empty for empty input', () => {
    expect(parseVars('')).toEqual({});
  });
});

// --- 6 forbidden patterns ---

describe('forbidden CSS patterns', () => {
  const cases: Array<[string, RegExp]> = [
    ['@import url("evil.css")', /import/i],
    ['expression(alert(1))', /expression/i],
    ['behavior: url(x.htc)', /behavior/i],
    ['background: javascript:alert(1)', /javascript/i],
    ['background: url(https://evil.com/x.css)', /https?:/i],
    ['background: url(data:text/html,<script>alert(1)</script>)', /data:/i],
    ['-moz-binding: url(x.xml)', /-moz-binding/i],
    ['@charset "UTF-8";', /@charset/i],
  ];
  for (const [css, hint] of cases) {
    it(`rejects ${hint}`, () => {
      const result = validateCss(css);
      expect(result.valid).toBe(false);
      expect(result.errors?.some((e) => hint.test(e))).toBe(true);
    });
  }
});

// --- length limits ---

describe('length limits', () => {
  it('rejects single line over MAX_LINE_LENGTH', () => {
    const css = `:root { --color-bg: "${'a'.repeat(MAX_LINE_LENGTH + 1)}"; }`;
    const result = validateCss(css);
    expect(result.valid).toBe(false);
    expect(result.errors?.some((e) => e.includes('LINE_TOO_LONG'))).toBe(true);
  });
  it('rejects total CSS over MAX_TOTAL_LENGTH', () => {
    const css = 'a'.repeat(MAX_TOTAL_LENGTH + 1);
    const result = validateCss(css);
    expect(result.valid).toBe(false);
    expect(result.errors?.some((e) => e.includes('CSS_TOO_LARGE'))).toBe(true);
  });
  it('accepts CSS at exact MAX_TOTAL_LENGTH', () => {
    // Build padding using short whitespace lines so total length == MAX_TOTAL_LENGTH
    // and each individual line <= MAX_LINE_LENGTH.
    const head = ':root { --color-bg: #fff; }';
    const target = MAX_TOTAL_LENGTH;
    const fillerLen = target - head.length - 1; // -1 for the joining newline
    const lineLen = 100; // <= MAX_LINE_LENGTH
    const numLines = Math.floor(fillerLen / (lineLen + 1));
    const used = numLines * (lineLen + 1);
    const lastLineLen = fillerLen - used;
    const padding = (' '.repeat(lineLen) + '\n').repeat(numLines) + ' '.repeat(lastLineLen);
    const css = head + '\n' + padding;
    expect(css.length).toBe(MAX_TOTAL_LENGTH);
    const result = validateCss(css);
    expect(result.valid).toBe(true);
  });
});

// --- var whitelist enforcement ---

describe('var whitelist', () => {
  it('rejects non-whitelisted var', () => {
    const css = ':root { --evil-var: red; }';
    const result = validateCss(css);
    expect(result.valid).toBe(false);
    expect(result.errors?.some((e) => e.includes('VAR_NOT_ALLOWED'))).toBe(true);
  });
  it('rejects misspelled whitelisted var', () => {
    const css = ':root { --color-bg-typo: red; }';
    const result = validateCss(css);
    expect(result.valid).toBe(false);
    expect(result.errors?.some((e) => e.includes('--color-bg-typo'))).toBe(true);
  });
});

// --- valid cases ---

describe('valid CSS', () => {
  it('accepts empty string', () => {
    expect(validateCss('').valid).toBe(true);
  });
  it('accepts CSS comment only', () => {
    expect(validateCss('/* just a comment */').valid).toBe(true);
  });
  it('accepts full theme with all 16 vars', () => {
    const lines = ALLOWED_CSS_VARS.map((v) => `${v}: #000;`).join(' ');
    const css = `:root { ${lines} }`;
    expect(validateCss(css).valid).toBe(true);
  });
  it('accepts :root + multiple selectors (only :root vars count)', () => {
    const css = `
      :root { --color-bg: #fff; }
      body { color: red; }
    `;
    expect(validateCss(css).valid).toBe(true);
  });
});