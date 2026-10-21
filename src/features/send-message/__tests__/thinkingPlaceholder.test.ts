import { describe, expect, it } from 'vitest';

import {
  THINKING_PLACEHOLDER,
  isThinkingPlaceholder,
  formatThinkingPlaceholderSummary,
  formatThinkingPlaceholderJson,
} from '../thinkingPlaceholder';

describe('thinkingPlaceholder audit helpers', () => {
  it('formats thinking placeholder summary and json', () => {
    expect(isThinkingPlaceholder(THINKING_PLACEHOLDER)).toBe(true);
    expect(formatThinkingPlaceholderSummary(THINKING_PLACEHOLDER)).toBe(
      `placeholder=true · length=${THINKING_PLACEHOLDER.length}`,
    );
    const parsed = JSON.parse(formatThinkingPlaceholderJson(THINKING_PLACEHOLDER));
    expect(parsed).toEqual({
      placeholder: true,
      length: THINKING_PLACEHOLDER.length,
      sentinel: THINKING_PLACEHOLDER,
    });
  });

  it('handles normal text and nullish inputs safely', () => {
    expect(isThinkingPlaceholder('hello')).toBe(false);
    expect(formatThinkingPlaceholderSummary(null)).toBe('placeholder=false · length=0');
    expect(JSON.parse(formatThinkingPlaceholderJson(undefined)).placeholder).toBe(false);
  });
});
