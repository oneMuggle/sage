import { describe, expect, it } from 'vitest';

import { MAX_DIFF_INPUT_CHARS, diffSpans } from '../textDiff';

describe('diffSpans', () => {
  it('returns a single same-span for identical input', () => {
    const { before, after } = diffSpans('abc', 'abc');
    expect(before).toEqual([{ text: 'abc', kind: 'same' }]);
    expect(after).toEqual([{ text: 'abc', kind: 'same' }]);
  });

  it('marks a mid-string replacement as del + add with shared edges', () => {
    const { before, after } = diffSpans('上下文 大模型 医学', '上下文 LLM 医学');
    expect(before).toEqual([
      { text: '上下文 ', kind: 'same' },
      { text: '大模型', kind: 'del' },
      { text: ' 医学', kind: 'same' },
    ]);
    expect(after).toEqual([
      { text: '上下文 ', kind: 'same' },
      { text: 'LLM', kind: 'add' },
      { text: ' 医学', kind: 'same' },
    ]);
  });

  it('marks pure insertion as add only', () => {
    const { before, after } = diffSpans('abcdef', 'abcXYZdef');
    expect(before.every((s) => s.kind !== 'add')).toBe(true);
    expect(after.filter((s) => s.kind === 'add')).toEqual([{ text: 'XYZ', kind: 'add' }]);
  });

  it('marks pure deletion as del only', () => {
    const { before, after } = diffSpans('abcXYZdef', 'abcdef');
    expect(after.every((s) => s.kind !== 'del')).toBe(true);
    expect(before.filter((s) => s.kind === 'del')).toEqual([{ text: 'XYZ', kind: 'del' }]);
  });

  it('handles empty sides', () => {
    expect(diffSpans('', 'abc')).toEqual({
      before: [],
      after: [{ text: 'abc', kind: 'add' }],
    });
    expect(diffSpans('abc', '')).toEqual({
      before: [{ text: 'abc', kind: 'del' }],
      after: [],
    });
  });

  it('degrades to whole-segment marks over the input guard', () => {
    const big = 'x'.repeat(MAX_DIFF_INPUT_CHARS + 1);
    const { before, after } = diffSpans(big, `${big}y`);
    expect(before).toEqual([{ text: big, kind: 'del' }]);
    expect(after).toEqual([{ text: `${big}y`, kind: 'add' }]);
  });

  it('merges consecutive same-kind spans (no adjacent duplicates)', () => {
    const { after } = diffSpans('a1b2c', 'aXbYc');
    const kinds = after.map((s) => s.kind);
    for (let i = 1; i < kinds.length; i++) {
      expect(kinds[i]).not.toBe(kinds[i - 1]);
    }
  });
});
