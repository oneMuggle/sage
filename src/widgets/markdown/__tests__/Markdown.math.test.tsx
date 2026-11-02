/**
 * KaTeX 数学公式渲染测试。
 *
 * 覆盖：
 * - inline math（$...$）
 * - display math（$$...$$）
 * - 混合 inline + display
 * - rehype-katex 输出 .katex 容器
 */

import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Markdown } from '../index';

describe('Markdown — inline math', () => {
  it('renders $...$ as inline KaTeX', () => {
    const src = 'Einstein equation: $E=mc^2$';
    const { container } = render(<Markdown content={src} />);
    // rehype-katex wraps math in .katex span
    const katex = container.querySelector('.katex');
    expect(katex).toBeTruthy();
  });

  it('renders multiple inline math expressions', () => {
    const src = 'Both $x$ and $y$ are positive';
    const { container } = render(<Markdown content={src} />);
    const katexSpans = container.querySelectorAll('.katex');
    expect(katexSpans.length).toBe(2);
  });
});

describe('Markdown — display math', () => {
  it('renders $$...$$ as display KaTeX', () => {
    const src = `$$
\\int_0^1 f(x) dx
$$`;
    const { container } = render(<Markdown content={src} />);
    const katex = container.querySelector('.katex');
    expect(katex).toBeTruthy();
  });
});

describe('Markdown — mixed inline and display math', () => {
  it('renders both in the same document', () => {
    const src = `Given $a$ and $b$:

$$
a^2 + b^2 = c^2
$$

Then $c$ is the hypotenuse.`;
    const { container } = render(<Markdown content={src} />);
    const katexSpans = container.querySelectorAll('.katex');
    // 3 inline ($a$, $b$, $c$) + 1 display = 4 katex spans
    expect(katexSpans.length).toBeGreaterThanOrEqual(3);
  });
});
