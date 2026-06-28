import { ALLOWED_CSS_VARS } from '../../shared/types/theme';
import { parseVars } from '../../shared/lib/theme/cssValidator';

const ALLOWED_SET: ReadonlySet<string> = new Set(ALLOWED_CSS_VARS);

/**
 * Inject a set of CSS variables onto document.documentElement.style.
 * Only whitelisted vars are written; non-whitelisted are silently ignored.
 */
export function injectVars(vars: Record<string, string>): void {
  for (const [name, value] of Object.entries(vars)) {
    if (!ALLOWED_SET.has(name)) {
      continue;
    }
    document.documentElement.style.setProperty(name, String(value));
  }
}

/**
 * Remove all 16 whitelisted vars from document.documentElement.style.
 * Use this when switching presets or rolling back custom CSS.
 */
export function clearVars(): void {
  for (const name of ALLOWED_CSS_VARS) {
    document.documentElement.style.removeProperty(name);
  }
}

/**
 * Parse raw CSS, extract vars from :root, and inject them.
 * Returns the vars that were injected (for verification).
 */
export function injectFromCss(css: string): Record<string, string> {
  const vars = parseVars(css);
  injectVars(vars);
  return vars;
}