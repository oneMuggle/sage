// 测试 buildSearchSnippet：短正文原样返回，长正文把命中位置压进可视窗口。

import { describe, expect, it } from 'vitest';

import { SEARCH_SNIPPET_MAX_CHARS, buildSearchSnippet } from '../searchSnippet';

describe('buildSearchSnippet', () => {
  it('returns short bodies unchanged', () => {
    expect(buildSearchSnippet('导出后中文变乱码，见截图', '乱码')).toBe('导出后中文变乱码，见截图');
  });

  it('collapses whitespace and trims', () => {
    expect(buildSearchSnippet('  a\n\n b\tc  ', 'b')).toBe('a b c');
  });

  it('centers the window on the match with ellipses on both sides', () => {
    const body = 'a'.repeat(200) + 'NEEDLE' + 'b'.repeat(200);
    const snippet = buildSearchSnippet(body, 'NEEDLE');
    expect(snippet).toContain('NEEDLE');
    expect(snippet.startsWith('…')).toBe(true);
    expect(snippet.endsWith('…')).toBe(true);
    expect(snippet.replace(/…/g, '').length).toBe(SEARCH_SNIPPET_MAX_CHARS);
  });

  it('matches case-insensitively for ASCII', () => {
    const body = 'x'.repeat(200) + 'Needle' + 'y'.repeat(200);
    expect(buildSearchSnippet(body, 'needle')).toContain('Needle');
  });

  it('falls back to the head when the query is absent', () => {
    const body = 'a'.repeat(200);
    const snippet = buildSearchSnippet(body, 'zzz');
    expect(snippet).toBe(`${'a'.repeat(SEARCH_SNIPPET_MAX_CHARS)}…`);
  });

  it('only ellipsizes the trailing side when the match is near the end', () => {
    const body = 'a'.repeat(200) + 'NEEDLE';
    const snippet = buildSearchSnippet(body, 'NEEDLE');
    expect(snippet.startsWith('…')).toBe(true);
    expect(snippet.endsWith('NEEDLE')).toBe(true);
  });

  it('honors a custom maxChars', () => {
    const snippet = buildSearchSnippet('0123456789abcdef', 'abc', 6);
    expect(snippet).toContain('abc');
    expect(snippet.replace(/…/g, '').length).toBe(6);
  });

  it('handles an empty query by showing the head', () => {
    expect(buildSearchSnippet('a'.repeat(200), '')).toBe(
      `${'a'.repeat(SEARCH_SNIPPET_MAX_CHARS)}…`,
    );
  });
});
