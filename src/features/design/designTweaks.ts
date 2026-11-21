/**
 * Design tweaks helpers — pure functions for token overrides.
 *
 * `applyTweaks` injects a <style> block with CSS variable overrides into the
 * artifact HTML so the preview reflects tweaks without regenerating.
 * `extractTweakDefaults` parses a design system's tokens.css to initialize
 * panel controls with the system's own values.
 */
import type { ProjectTweaks } from '../../entities/design/types';

export interface TweakDefaults {
  accent: string;
  radius: number;
  fontSize: number;
  density: number;
  fontFamily: string;
}

const FALLBACK_DEFAULTS: TweakDefaults = {
  accent: '#000000',
  radius: 6,
  fontSize: 16,
  density: 16,
  fontFamily: '',
};

function parsePx(css: string, name: string, fallback: number): number {
  const match = css.match(new RegExp(`${name}\\s*:\\s*([\\d.]+)(px|rem)`));
  if (!match) return fallback;
  const value = parseFloat(match[1]);
  return match[2] === 'rem' ? Math.round(value * 16) : Math.round(value);
}

/** Parse system tokens.css into panel defaults. */
export function extractTweakDefaults(tokensCss: string): TweakDefaults {
  const accentMatch =
    tokensCss.match(/--color-accent\s*:\s*(#[0-9a-fA-F]{3,8})/) ??
    tokensCss.match(/--color-primary\s*:\s*(#[0-9a-fA-F]{3,8})/);
  const fontMatch = tokensCss.match(/--font-family\s*:\s*([^;]+);/);
  return {
    accent: accentMatch?.[1] ?? FALLBACK_DEFAULTS.accent,
    radius: parsePx(tokensCss, '--border-radius', FALLBACK_DEFAULTS.radius),
    fontSize: parsePx(tokensCss, '--font-size-base', FALLBACK_DEFAULTS.fontSize),
    density: parsePx(tokensCss, '--space-4', FALLBACK_DEFAULTS.density),
    fontFamily: fontMatch?.[1].trim() ?? FALLBACK_DEFAULTS.fontFamily,
  };
}

/** Build the CSS override declarations for the given tweaks (only set fields). */
export function tweakCssDeclarations(tweaks: ProjectTweaks): string[] {
  const declarations: string[] = [];
  if (tweaks.accent) {
    declarations.push(`--color-accent: ${tweaks.accent};`, `--color-primary: ${tweaks.accent};`);
  }
  if (tweaks.radius != null) {
    declarations.push(
      `--border-radius: ${tweaks.radius}px;`,
      `--border-radius-sm: ${tweaks.radius}px;`,
      `--border-radius-lg: ${Math.min(tweaks.radius + 2, 24)}px;`,
    );
  }
  if (tweaks.font_size != null) {
    declarations.push(`--font-size-base: ${tweaks.font_size}px;`);
  }
  if (tweaks.font_family) {
    declarations.push(`--font-family: ${tweaks.font_family};`);
  }
  if (tweaks.density != null) {
    declarations.push(`--space-4: ${tweaks.density}px;`);
  }
  return declarations;
}

/** Inject a tweaks <style> block into the artifact HTML. */
export function applyTweaks(html: string, tweaks: ProjectTweaks): string {
  const declarations = tweakCssDeclarations(tweaks);
  if (declarations.length === 0) return html;
  const style = `<style id="sage-design-tweaks">:root{${declarations.join(' ')}}</style>`;
  return html.includes('</head>') ? html.replace('</head>', `${style}</head>`) : `${style}${html}`;
}
