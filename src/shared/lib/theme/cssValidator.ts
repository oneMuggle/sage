import { ALLOWED_CSS_VARS, type ThemeValidationResult } from '../../types/theme';

export const MAX_LINE_LENGTH = 1000;
export const MAX_TOTAL_LENGTH = 50_000;

const ALLOWED_VARS_SET: ReadonlySet<string> = new Set(ALLOWED_CSS_VARS);

const FORBIDDEN_PATTERNS: ReadonlyArray<[RegExp, string]> = [
  [/@import/i, '@import not allowed'],
  [/expression\s*\(/i, 'expression() not allowed'],
  [/behavior\s*:/i, 'behavior: not allowed'],
  [/javascript:/i, 'javascript: URL not allowed'],
  [/url\s*\(\s*['"]?\s*https?:/i, 'external URL https: not allowed'],
  [/url\s*\(\s*['"]?\s*data:/i, 'data: URL not allowed'],
  [/-moz-binding/i, '-moz-binding not allowed'],
  [/@charset/i, '@charset not allowed'],
];

const VAR_DECL_PATTERN = /(--[a-z0-9-]+)\s*:\s*([^;]+);/g;
const ROOT_BLOCK_PATTERN = /:root\s*\{([^}]*)\}/g;

/**
 * Extract --var: value pairs from :root blocks only.
 */
export function parseVars(css: string): Record<string, string> {
  const vars: Record<string, string> = {};
  let match: RegExpExecArray | null;
  // Reset regex state
  ROOT_BLOCK_PATTERN.lastIndex = 0;
  while ((match = ROOT_BLOCK_PATTERN.exec(css)) !== null) {
    const body = match[1];
    VAR_DECL_PATTERN.lastIndex = 0;
    let varMatch: RegExpExecArray | null;
    while ((varMatch = VAR_DECL_PATTERN.exec(body)) !== null) {
      const varName = varMatch[1];
      const varValue = varMatch[2].trim();
      vars[varName] = varValue;
    }
  }
  return vars;
}

/**
 * Validate raw CSS string against 16-var whitelist + 6 forbidden patterns + length limits.
 */
export function validateCss(css: string): ThemeValidationResult {
  const errors: string[] = [];

  if (css.length > MAX_TOTAL_LENGTH) {
    return {
      valid: false,
      errors: [`CSS_TOO_LARGE: total length ${css.length} > ${MAX_TOTAL_LENGTH}`],
    };
  }

  // Per-line checks
  const lines = css.split('\n');
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.length > MAX_LINE_LENGTH) {
      errors.push(`LINE_TOO_LONG: line ${i + 1} > ${MAX_LINE_LENGTH} chars`);
    }
    for (const [pattern, message] of FORBIDDEN_PATTERNS) {
      if (pattern.test(line)) {
        errors.push(`line ${i + 1}: ${message}`);
      }
    }
  }

  // Whitelist check: extract all --var: declarations (any selector, conservative)
  const allVars = new Set<string>();
  const globalPattern = /(--[a-z0-9-]+)\s*:/g;
  let m: RegExpExecArray | null;
  while ((m = globalPattern.exec(css)) !== null) {
    allVars.add(m[1]);
  }
  for (const v of allVars) {
    if (!ALLOWED_VARS_SET.has(v)) {
      errors.push(`VAR_NOT_ALLOWED: ${v}`);
    }
  }

  return errors.length === 0 ? { valid: true } : { valid: false, errors };
}
