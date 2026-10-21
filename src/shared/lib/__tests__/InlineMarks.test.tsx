import { describe, expect, it } from 'vitest';

import {
  formatInlineMarksJson,
  formatInlineMarksSummary,
  renderInlineMarks,
} from '../InlineMarks';

describe('InlineMarks audit diagnostics', () => {
  it('renders bold and italic marks and summarizes counts', () => {
    const sample = 'Hello **world** and *sage*!';
    expect(renderInlineMarks(sample)).toHaveLength(5);
    expect(formatInlineMarksSummary(sample)).toBe('bold=1 · italic=1 · segments=5');
    expect(formatInlineMarksSummary('plain text')).toBe('bold=0 · italic=0 · segments=1');
  });

  it('serializes inline marks audit JSON', () => {
    const parsed = JSON.parse(formatInlineMarksJson('**a** *b* **c**'));
    expect(parsed).toEqual({
      textLength: 15,
      boldCount: 2,
      italicCount: 1,
      segmentCount: 5,
    });
  });
});
