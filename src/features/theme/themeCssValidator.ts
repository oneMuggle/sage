/**
 * CSS 主题校验器 — 16 变量白名单 + 危险模式拒绝
 *
 * 纯函数，不依赖 React / DOM。
 *
 * 安全约束：
 * 1. 必须包含 :root 选择器
 * 2. 拒绝 @import / expression() / 外链 url() / <script> / javascript: / behavior:
 * 3. 仅允许 16 个白名单 CSS 变量
 */

export interface ValidationResult {
  ok: boolean;
  error?: string;
}

const ALLOWED_VARS: ReadonlySet<string> = new Set([
  '--bg-base', '--bg-1', '--bg-2', '--bg-3', '--bg-4', '--bg-5',
  '--text-primary', '--text-secondary', '--text-muted',
  '--primary', '--primary-hover',
  '--border-base',
  '--success', '--error', '--warning', '--info',
]);

/**
 * 危险模式正则 — 匹配即拒绝。
 * data: URL 允许（用于封面图），外链 url() 拒绝。
 */
const FORBIDDEN_PATTERNS: ReadonlyArray<{ pattern: RegExp; message: string }> = [
  { pattern: /@import\b/i, message: '@import is not allowed' },
  { pattern: /expression\s*\(/i, message: 'expression() is not allowed' },
  { pattern: /url\s*\(\s*["']?(?:https?:|\/\/)/i, message: 'external url() is not allowed' },
  { pattern: /<script\b/i, message: '<script> is not allowed' },
  { pattern: /javascript:/i, message: 'javascript: protocol is not allowed' },
  { pattern: /behavior\s*:/i, message: 'behavior: is not allowed' },
];

/** CSS 变量声明匹配: --var-name: value; */
const VAR_DECL_RE = /(--[a-z0-9][a-z0-9-]*)\s*:\s*([^;]+)/gi;

/** :root 选择器检测 */
const ROOT_SELECTOR_RE = /:root\b/;

export const themeCssValidator = {
  validate(css: string): ValidationResult {
    // 1. 空检查
    if (!css || css.trim().length === 0) {
      return { ok: false, error: 'CSS must not be empty' };
    }

    // 2. 必须包含 :root
    if (!ROOT_SELECTOR_RE.test(css)) {
      return { ok: false, error: 'CSS must contain a :root selector' };
    }

    // 3. 拒绝危险模式
    for (const { pattern, message } of FORBIDDEN_PATTERNS) {
      if (pattern.test(css)) {
        return { ok: false, error: message };
      }
    }

    // 4. 检查所有变量声明是否在白名单
    const varMatches = css.matchAll(VAR_DECL_RE);
    for (const match of varMatches) {
      const varName = match[1].toLowerCase();
      if (!ALLOWED_VARS.has(varName)) {
        return {
          ok: false,
          error: `Variable "${varName}" is not in the allowlist`,
        };
      }
    }

    return { ok: true };
  },

  extractVars(css: string): Map<string, string> {
    const vars = new Map<string, string>();
    const varMatches = css.matchAll(VAR_DECL_RE);
    for (const match of varMatches) {
      const varName = match[1].toLowerCase();
      const value = match[2].trim();
      vars.set(varName, value);
    }
    return vars;
  },
};
