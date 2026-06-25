import { describe, expect, it } from 'vitest';
import { themeCssValidator } from '../themeCssValidator';

describe('themeCssValidator', () => {
  describe('validate', () => {
    describe('valid CSS', () => {
      it('accepts CSS with :root and whitelisted variables', () => {
        const css = ':root { --bg-base: #ffffff; --primary: #4f46e5; }';
        const result = themeCssValidator.validate(css);
        expect(result.ok).toBe(true);
        expect(result.error).toBeUndefined();
      });

      it('accepts CSS with all 16 whitelisted variables', () => {
        const css = `:root {
  --bg-base: #fff;
  --bg-1: #f5f5f5;
  --bg-2: #e5e5e5;
  --bg-3: #d5d5d5;
  --bg-4: #c5c5c5;
  --bg-5: #b5b5b5;
  --text-primary: #111;
  --text-secondary: #555;
  --text-muted: #999;
  --primary: #4f46e5;
  --primary-hover: #4338ca;
  --border-base: #e5e7eb;
  --success: #10b981;
  --error: #ef4444;
  --warning: #f59e0b;
  --info: #3b82f6;
}`;
        const result = themeCssValidator.validate(css);
        expect(result.ok).toBe(true);
      });

      it('accepts CSS with data: URL in background-image', () => {
        const css = ':root { --bg-base: url("data:image/svg+xml,%3Csvg..."); }';
        const result = themeCssValidator.validate(css);
        expect(result.ok).toBe(true);
      });
    });

    describe('missing :root', () => {
      it('rejects CSS without :root selector', () => {
        const css = '.theme { --bg-base: #fff; }';
        const result = themeCssValidator.validate(css);
        expect(result.ok).toBe(false);
        expect(result.error).toMatch(/:root/);
      });

      it('rejects empty CSS', () => {
        const result = themeCssValidator.validate('');
        expect(result.ok).toBe(false);
        expect(result.error).toBeDefined();
      });

      it('rejects whitespace-only CSS', () => {
        const result = themeCssValidator.validate('   \n\t  ');
        expect(result.ok).toBe(false);
        expect(result.error).toBeDefined();
      });
    });

    describe('forbidden patterns', () => {
      it('rejects CSS with @import', () => {
        const css = ':root { @import url("evil.css"); --bg-base: #fff; }';
        const result = themeCssValidator.validate(css);
        expect(result.ok).toBe(false);
        expect(result.error).toMatch(/@import/i);
      });

      it('rejects CSS with expression()', () => {
        const css = ':root { --bg-base: expression(alert(1)); }';
        const result = themeCssValidator.validate(css);
        expect(result.ok).toBe(false);
        expect(result.error).toMatch(/expression/i);
      });

      it('rejects CSS with external url() (http://)', () => {
        const css = ':root { --bg-base: url("http://evil.com/x.png"); }';
        const result = themeCssValidator.validate(css);
        expect(result.ok).toBe(false);
        expect(result.error).toMatch(/url/i);
      });

      it('rejects CSS with external url() (https://)', () => {
        const css = ':root { --bg-base: url("https://evil.com/x.png"); }';
        const result = themeCssValidator.validate(css);
        expect(result.ok).toBe(false);
        expect(result.error).toMatch(/url/i);
      });

      it('rejects CSS with external url() (protocol-relative)', () => {
        const css = ':root { --bg-base: url("//evil.com/x.png"); }';
        const result = themeCssValidator.validate(css);
        expect(result.ok).toBe(false);
        expect(result.error).toMatch(/url/i);
      });

      it('rejects CSS with <script>', () => {
        const css = ':root { --bg-base: #fff; } <script>alert(1)</script>';
        const result = themeCssValidator.validate(css);
        expect(result.ok).toBe(false);
        expect(result.error).toMatch(/script/i);
      });

      it('rejects CSS with javascript: protocol', () => {
        const css = ':root { --bg-base: url("javascript:alert(1)"); }';
        const result = themeCssValidator.validate(css);
        expect(result.ok).toBe(false);
        expect(result.error).toMatch(/javascript:/i);
      });

      it('rejects CSS with behavior:', () => {
        const css = ':root { --bg-base: #fff; behavior: url(xss.htc); }';
        const result = themeCssValidator.validate(css);
        expect(result.ok).toBe(false);
        expect(result.error).toMatch(/behavior/i);
      });
    });

    describe('non-whitelisted variables', () => {
      it('rejects CSS with non-whitelisted variable', () => {
        const css = ':root { --evil-var: red; }';
        const result = themeCssValidator.validate(css);
        expect(result.ok).toBe(false);
        expect(result.error).toMatch(/not allowed|whitelist|allowlist/i);
      });

      it('rejects CSS with multiple non-whitelisted variables', () => {
        const css = ':root { --bg-base: #fff; --custom-color: red; }';
        const result = themeCssValidator.validate(css);
        expect(result.ok).toBe(false);
        expect(result.error).toMatch(/--custom-color/);
      });

      it('accepts CSS with only whitelisted variables', () => {
        const css = ':root { --bg-base: #fff; --primary: #000; --text-primary: #333; }';
        const result = themeCssValidator.validate(css);
        expect(result.ok).toBe(true);
      });
    });
  });

  describe('extractVars', () => {
    it('extracts variable names and values from CSS', () => {
      const css = ':root { --bg-base: #ffffff; --primary: #4f46e5; }';
      const vars = themeCssValidator.extractVars(css);
      expect(vars.size).toBe(2);
      expect(vars.get('--bg-base')).toBe('#ffffff');
      expect(vars.get('--primary')).toBe('#4f46e5');
    });

    it('handles multi-line CSS', () => {
      const css = `:root {
  --bg-base: #fff;
  --primary: #000;
}`;
      const vars = themeCssValidator.extractVars(css);
      expect(vars.size).toBe(2);
      expect(vars.get('--bg-base')).toBe('#fff');
      expect(vars.get('--primary')).toBe('#000');
    });

    it('trims whitespace from values', () => {
      const css = ':root { --bg-base:   #fff  ; }';
      const vars = themeCssValidator.extractVars(css);
      expect(vars.get('--bg-base')).toBe('#fff');
    });

    it('returns empty map for CSS without variables', () => {
      const css = ':root { background: red; }';
      const vars = themeCssValidator.extractVars(css);
      expect(vars.size).toBe(0);
    });

    it('handles values with special characters', () => {
      const css = ':root { --bg-base: url("data:image/svg+xml,%3Csvg"); }';
      const vars = themeCssValidator.extractVars(css);
      expect(vars.has('--bg-base')).toBe(true);
    });

    it('handles multiple declarations of same variable (last wins)', () => {
      const css = ':root { --bg-base: #fff; --bg-base: #000; }';
      const vars = themeCssValidator.extractVars(css);
      expect(vars.get('--bg-base')).toBe('#000');
    });
  });
});
