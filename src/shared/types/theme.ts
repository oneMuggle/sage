/**
 * Theme domain types shared between frontend and backend.
 * Mirrors backend/schemas/theme.py.
 */

export interface ThemePreset {
  id: string; // 'light' | 'dark' | 'ocean' | 'forest' | 'sunset' | user-*
  name: string; // i18n key
  description: string; // i18n key
  cover?: string; // URL or relative path
  css?: string; // optional raw CSS for user-saved themes
}

export interface ThemeCssPayload {
  css: string; // raw CSS string
  vars: Record<string, string>; // parsed 16-var whitelist
}

export interface ActiveTheme {
  presetId: string;
  customCss?: string;
}

export interface ThemeValidationResult {
  valid: boolean;
  errors?: string[];
}

/**
 * The 16 CSS variables that theme CSS is allowed to override.
 * Mirrors backend ALLOWED_CSS_VARS in backend/api/theme_router.py.
 * Adding/removing vars requires updating BOTH sides + adding test cases.
 */
export const ALLOWED_CSS_VARS = [
  '--color-bg',
  '--color-bg-secondary',
  '--color-bg-tertiary',
  '--color-fg',
  '--color-fg-secondary',
  '--color-fg-muted',
  '--color-border',
  '--color-border-strong',
  '--color-accent',
  '--color-accent-hover',
  '--color-success',
  '--color-warning',
  '--color-error',
  '--color-info',
  '--color-link',
  '--color-link-hover',
] as const;

export type AllowedCssVar = (typeof ALLOWED_CSS_VARS)[number];
