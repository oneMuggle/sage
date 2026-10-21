import { describe, expect, it } from 'vitest';

import {
  truncate,
  formatTextTruncateSummary,
  formatTextTruncateJson,
} from '../utils';

describe('shared/lib/utils audit helpers', () => {
  it('truncates text and formats summary and json', () => {
    expect(truncate('abcdef', 4)).toBe('abcd...');
    expect(formatTextTruncateSummary('abcdef', 4)).toBe(
      'length=6 · max=4 · truncated=true',
    );
    const parsed = JSON.parse(formatTextTruncateJson('abcdef', 4));
    expect(parsed).toEqual({
      originalLength: 6,
      maxLength: 4,
      truncated: true,
      preview: 'abcd...',
    });
  });

  it('handles short or nullish text safely', () => {
    expect(formatTextTruncateSummary(null, 10)).toBe(
      'length=0 · max=10 · truncated=false',
    );
    expect(JSON.parse(formatTextTruncateJson('hi', 10)).truncated).toBe(false);
  });
});
