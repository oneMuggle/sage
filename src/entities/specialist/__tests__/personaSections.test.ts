import { describe, expect, it } from 'vitest';

import {
  emptyPersonaSections,
  isPersonaEmpty,
  parsePersonaSections,
  serializePersonaSections,
} from '../personaSections';

describe('personaSections', () => {
  describe('emptyPersonaSections', () => {
    it('returns an all-empty section map', () => {
      expect(emptyPersonaSections()).toEqual({
        identity: '',
        responsibilities: '',
        workflow: '',
        style: '',
        guardrails: '',
        output: '',
      });
    });
  });

  describe('isPersonaEmpty', () => {
    it('treats a fully empty map as empty', () => {
      expect(isPersonaEmpty(emptyPersonaSections())).toBe(true);
    });

    it('treats a map with only whitespace as empty', () => {
      expect(isPersonaEmpty({ ...emptyPersonaSections(), identity: '   \n\t' })).toBe(true);
    });

    it('is false when any section has non-empty content', () => {
      const sections = { ...emptyPersonaSections(), style: '温和' };
      expect(isPersonaEmpty(sections)).toBe(false);
    });
  });

  describe('serializePersonaSections', () => {
    it('skips empty sections and preserves fixed order', () => {
      const sections = {
        identity: '你是写作专家。',
        responsibilities: '- 润色\n- 改写',
        workflow: '',
        style: '',
        guardrails: '- 保持原意',
        output: '',
      };
      expect(serializePersonaSections(sections)).toBe(
        '# 身份\n\n你是写作专家。\n\n# 职责\n\n- 润色\n- 改写\n\n# 行为边界\n\n- 保持原意',
      );
    });

    it('returns empty string when all sections are empty', () => {
      expect(serializePersonaSections(emptyPersonaSections())).toBe('');
    });
  });

  describe('parsePersonaSections', () => {
    it('splits markdown by canonical H1 headings', () => {
      const md = `# 身份

你是写作专家。

# 职责

- 润色
- 改写

# 行为边界

- 保持原意`;
      const result = parsePersonaSections(md);
      expect(result.identity).toBe('你是写作专家。');
      expect(result.responsibilities).toBe('- 润色\n- 改写');
      expect(result.guardrails).toBe('- 保持原意');
      expect(result.workflow).toBe('');
      expect(result.style).toBe('');
      expect(result.output).toBe('');
    });

    it('accepts alias headings (角色 / 工作流程 / 护栏)', () => {
      const md = `# 角色

定位身份。

# 工作流程

先通读。

# 护栏

不改核心意思。`;
      const result = parsePersonaSections(md);
      expect(result.identity).toBe('定位身份。');
      expect(result.workflow).toBe('先通读。');
      expect(result.guardrails).toBe('不改核心意思。');
    });

    it('routes preamble (text before first heading) into identity', () => {
      const md = `我是直接写在最前面的正文。

# 职责

- 一项任务`;
      const result = parsePersonaSections(md);
      expect(result.identity).toContain('我是直接写在最前面的正文。');
      expect(result.responsibilities).toBe('- 一项任务');
    });

    it('preserves unknown H1 headings as body text in current section', () => {
      const md = `# 身份

先介绍。

# 未知段落

这段应当保留。

# 职责

继续写。`;
      const result = parsePersonaSections(md);
      // Unknown heading's body lines are preserved in the current section (identity).
      expect(result.identity).toContain('先介绍。');
      expect(result.identity).toContain('# 未知段落');
      expect(result.identity).toContain('这段应当保留。');
      expect(result.responsibilities).toBe('继续写。');
    });

    it('trims whitespace around each section body', () => {
      const md = `# 身份


   前后都是空白行


# 职责

   - 任务   `;
      const result = parsePersonaSections(md);
      expect(result.identity).toBe('前后都是空白行');
      expect(result.responsibilities).toBe('- 任务');
    });

    it('returns all-empty sections for empty input', () => {
      expect(parsePersonaSections('')).toEqual(emptyPersonaSections());
      // Also tolerates non-string input defensively.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      expect(parsePersonaSections(undefined as any)).toEqual(emptyPersonaSections());
    });
  });

  describe('round-trip', () => {
    it('serialize → parse reproduces sections', () => {
      const original = {
        identity: '你是写作专家。',
        responsibilities: '- 润色',
        workflow: '先通读，再修改。',
        style: '',
        guardrails: '- 保持原意',
        output: '',
      };
      const roundTripped = parsePersonaSections(serializePersonaSections(original));
      expect(roundTripped).toEqual(original);
    });
  });
});
