/**
 * Markdown 大纲抽取器单元测试。
 *
 * 覆盖：
 * - ATX 标题（# ~ ######）
 * - Setext 标题（=== / ---）
 * - fenced code block 内的 # 不被识别为标题
 * - slug 算法（中文 / 重复 / 特殊字符）
 * - buildMarkdownOutline 去重
 * - headingIdForLine 按行号 lookup
 */

import { describe, expect, it } from 'vitest';
import {
  buildMarkdownOutline,
  extractHeadings,
  headingIdForLine,
  slugifyHeading,
} from '../outline';

describe('slugifyHeading', () => {
  it('handles ASCII', () => {
    expect(slugifyHeading('Hello World')).toBe('hello-world');
  });

  it('handles Chinese', () => {
    expect(slugifyHeading('你好世界')).toBe('你好世界');
  });

  it('strips punctuation', () => {
    expect(slugifyHeading('Hello, World!')).toBe('hello-world');
  });

  it('collapses whitespace and dashes', () => {
    expect(slugifyHeading('  multiple   spaces -- here  ')).toBe('multiple-spaces-here');
  });

  it('falls back to "section" for empty after stripping', () => {
    expect(slugifyHeading('!!!')).toBe('section');
    expect(slugifyHeading('   ')).toBe('section');
  });
});

describe('extractHeadings', () => {
  it('extracts ATX headings h1-h6', () => {
    const src = `# h1
## h2
### h3
#### h4
##### h5
###### h6
####### not a heading`;
    const headings = extractHeadings(src);
    expect(headings.map((h) => h.level)).toEqual([1, 2, 3, 4, 5, 6]);
    expect(headings.map((h) => h.text)).toEqual(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']);
  });

  it('records 1-based line numbers', () => {
    const src = `\n# first\n\n## second`;
    const headings = extractHeadings(src);
    expect(headings[0].line).toBe(2);
    expect(headings[1].line).toBe(4);
  });

  it('extracts Setext headings (=== and ---)', () => {
    const src = `Title
=====

Subtitle
--------`;
    const headings = extractHeadings(src);
    expect(headings.map((h) => [h.level, h.text])).toEqual([
      [1, 'Title'],
      [2, 'Subtitle'],
    ]);
  });

  it('skips # inside fenced code blocks', () => {
    const src = `# real

\`\`\`bash
# this is a comment
echo hi
\`\`\`

## also real`;
    const headings = extractHeadings(src);
    expect(headings.map((h) => h.text)).toEqual(['real', 'also real']);
  });

  it('skips ~~~ fenced code blocks too', () => {
    const src = `# before
~~~python
# python comment
~~~
# after`;
    const headings = extractHeadings(src);
    expect(headings.map((h) => h.text)).toEqual(['before', 'after']);
  });

  it('strips inline markdown syntax from heading text', () => {
    const src = `# Hello **bold** and [link](url) with \`code\` and ~~strike~~`;
    const headings = extractHeadings(src);
    expect(headings[0].text).toBe('Hello bold and link with code and strike');
  });
});

describe('buildMarkdownOutline', () => {
  it('assigns ids with prefix', () => {
    const headings = extractHeadings('# Hello\n## World');
    const outline = buildMarkdownOutline(headings, 'doc');
    expect(outline.entries[0].id).toBe('doc-hello');
    expect(outline.entries[1].id).toBe('doc-world');
  });

  it('dedupes repeated slugs with -1, -2 suffixes', () => {
    const src = `# Foo\n# Foo\n# Foo`;
    const headings = extractHeadings(src);
    const outline = buildMarkdownOutline(headings, 'md');
    expect(outline.entries.map((e) => e.id)).toEqual(['md-foo', 'md-foo-1', 'md-foo-2']);
  });

  it('computes depth = level - 1', () => {
    const headings = extractHeadings('# h1\n### h3\n###### h6');
    const outline = buildMarkdownOutline(headings);
    expect(outline.entries.map((e) => e.depth)).toEqual([0, 2, 5]);
  });

  it('returns count equal to entries.length', () => {
    const outline = buildMarkdownOutline(extractHeadings('# a\n## b'));
    expect(outline.count).toBe(2);
  });
});

describe('headingIdForLine', () => {
  it('looks up id by 1-based line number', () => {
    const src = `# First\n\n## Second`;
    const headings = extractHeadings(src);
    expect(headingIdForLine(headings, 1)).toBe('md-first');
    expect(headingIdForLine(headings, 3)).toBe('md-second');
  });

  it('returns undefined for non-heading lines', () => {
    const headings = extractHeadings('# Only');
    expect(headingIdForLine(headings, 2)).toBeUndefined();
  });

  it('assigns -N suffix consistently with buildMarkdownOutline', () => {
    const src = `# Dup\n# Dup`;
    const headings = extractHeadings(src);
    const outline = buildMarkdownOutline(headings, 'md');
    expect(headingIdForLine(headings, 1, 'md')).toBe(outline.entries[0].id);
    expect(headingIdForLine(headings, 2, 'md')).toBe(outline.entries[1].id);
  });
});
