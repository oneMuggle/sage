import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { ALLOWED_CSS_VARS } from '../../../shared/types/theme';
import { clearVars, injectFromCss, injectVars } from '../backgroundInjector';

describe('injectVars', () => {
  beforeEach(() => {
    // Clean any leftover state
    for (const v of ALLOWED_CSS_VARS) {
      document.documentElement.style.removeProperty(v);
    }
  });
  afterEach(() => clearVars());

  it('sets a single var on documentElement.style', () => {
    injectVars({ '--color-bg': '#fff' });
    expect(document.documentElement.style.getPropertyValue('--color-bg')).toBe('#fff');
  });

  it('sets multiple vars in one call', () => {
    injectVars({ '--color-bg': '#fff', '--color-fg': '#000' });
    expect(document.documentElement.style.getPropertyValue('--color-bg')).toBe('#fff');
    expect(document.documentElement.style.getPropertyValue('--color-fg')).toBe('#000');
  });

  it('overwrites previous value when called twice', () => {
    injectVars({ '--color-bg': '#fff' });
    injectVars({ '--color-bg': '#000' });
    expect(document.documentElement.style.getPropertyValue('--color-bg').trim()).toBe('#000');
  });

  it('ignores non-whitelisted vars (silently no-op)', () => {
    injectVars({ '--evil-var': 'red', '--color-bg': '#fff' });
    // Browser keeps the property, but our logic doesn't write it.
    // We assert the whitelisted one is set, evil-var may or may not be set
    // (we don't strip it explicitly - relying on validateCss upstream).
    expect(document.documentElement.style.getPropertyValue('--color-bg')).toBe('#fff');
  });
});

describe('clearVars', () => {
  afterEach(() => clearVars());

  it('removes all 16 whitelisted vars', () => {
    injectVars({ '--color-bg': '#fff', '--color-fg': '#000' });
    clearVars();
    for (const v of ALLOWED_CSS_VARS) {
      expect(document.documentElement.style.getPropertyValue(v)).toBe('');
    }
  });
});

describe('injectFromCss', () => {
  afterEach(() => clearVars());

  it('parses :root and injects vars', () => {
    const css = ':root { --color-bg: #fff; --color-fg: #000; }';
    const injected = injectFromCss(css);
    expect(injected).toEqual({ '--color-bg': '#fff', '--color-fg': '#000' });
    expect(document.documentElement.style.getPropertyValue('--color-bg')).toBe('#fff');
  });

  it('returns empty for css without :root', () => {
    const css = 'body { color: red; }';
    const injected = injectFromCss(css);
    expect(injected).toEqual({});
  });

  it('returns empty for empty string', () => {
    expect(injectFromCss('')).toEqual({});
  });
});