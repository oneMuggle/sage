import { describe, expect, it } from 'vitest';

import { applyTweaks, applyTokensCss, extractTweakDefaults, tweakCssDeclarations } from '../designTweaks';

describe('designTweaks', () => {
  it('returns html unchanged when no overrides are set', () => {
    const html = '<html><head></head><body/></html>';
    expect(applyTweaks(html, {})).toBe(html);
    expect(tweakCssDeclarations({})).toEqual([]);
  });

  it('injects the override style block before </head>', () => {
    const html = '<html><head></head><body/></html>';
    const out = applyTweaks(html, { accent: '#ff0000', radius: 8 });
    expect(out).toContain('<style id="sage-design-tweaks">');
    expect(out).toContain('--color-accent: #ff0000;');
    expect(out).toContain('--border-radius: 8px;');
    expect(out.indexOf('sage-design-tweaks')).toBeLessThan(out.indexOf('</head>'));
  });

  it('prepends the style block when there is no head', () => {
    const out = applyTweaks('<div>x</div>', { font_size: 18 });
    expect(out.startsWith('<style')).toBe(true);
    expect(out).toContain('--font-size-base: 18px;');
    expect(out).toContain('<div>x</div>');
  });

  it('maps accent to both --color-accent and --color-primary', () => {
    const declarations = tweakCssDeclarations({ accent: '#123456' });
    expect(declarations).toContain('--color-accent: #123456;');
    expect(declarations).toContain('--color-primary: #123456;');
  });

  it('parses defaults from tokens.css (px / rem / hex)', () => {
    const css =
      ':root{--color-accent:#1a56db;--border-radius:6px;' +
      '--font-size-base:1rem;--space-4:2rem;}';
    const defaults = extractTweakDefaults(css);
    expect(defaults.accent).toBe('#1a56db');
    expect(defaults.radius).toBe(6);
    expect(defaults.fontSize).toBe(16);
    expect(defaults.density).toBe(32);
  });

  it('falls back to neutral defaults when tokens are missing', () => {
    expect(extractTweakDefaults('')).toEqual({
      accent: '#000000',
      radius: 6,
      fontSize: 16,
      density: 16,
      fontFamily: '',
    });
  });

  it('parses the font family token and injects it as an override', () => {
    const defaults = extractTweakDefaults(':root{--font-family: Georgia, serif;}');
    expect(defaults.fontFamily).toBe('Georgia, serif');

    const out = applyTweaks('<html><head></head><body/></html>', {
      font_family: 'Menlo, monospace',
    });
    expect(out).toContain('--font-family: Menlo, monospace;');
  });

  it('injects design-system tokens into an example document', () => {
    const out = applyTokensCss(
      '<html><head></head><body/></html>',
      ':root{--color-accent:#1a56db;}',
    );
    expect(out).toContain('<style id="sage-design-system">');
    expect(out).toContain('--color-accent:#1a56db;');
    expect(out.indexOf('sage-design-system')).toBeLessThan(out.indexOf('</head>'));
  });
});
