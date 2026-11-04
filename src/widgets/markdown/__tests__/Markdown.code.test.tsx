/**
 * 代码块渲染测试。
 *
 * 覆盖：
 * - inline code（`code`）
 * - fenced code（```lang ... ```）→ tier=chat 走 ShikiCodeBlock
 * - fenced code → tier=minimal 走 plain <pre><code>
 * - plainFences=true → 强制 plain pre/code
 * - unknown language fallback
 * - mermaid block → MermaidBlock（tier=chat only）
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { Markdown } from '../index';

// Mock heavy deps to avoid lazy-loading shiki/mermaid in unit tests
vi.mock('../../chat/ShikiCodeBlock', () => ({
  ShikiCodeBlock: ({ language, children }: { language?: string; children: string }) => (
    <div data-testid="shiki-code" data-language={language ?? ''}>
      {children}
    </div>
  ),
}));

vi.mock('../../chat/MermaidBlock', () => ({
  MermaidBlock: ({ code }: { code: string }) => (
    <div data-testid="mermaid-block">{code}</div>
  ),
}));

vi.mock('../../chat/MarkdownImage', () => ({
  MarkdownImage: ({ src, alt }: { src: string; alt?: string }) => (
    <img data-testid="md-image" src={src} alt={alt ?? ''} />
  ),
}));

describe('Markdown — inline code', () => {
  it('renders <code> for inline backticks', () => {
    const src = 'Use `console.log` to debug';
    const { container } = render(<Markdown content={src} />);
    const code = container.querySelector('code');
    expect(code).toBeTruthy();
    expect(code!.textContent).toBe('console.log');
  });
});

describe('Markdown — fenced code blocks (tier=chat)', () => {
  it('renders ShikiCodeBlock for known language', () => {
    const src = '```js\nconsole.log("hi")\n```';
    render(<Markdown content={src} tier="chat" />);
    const shiki = screen.getByTestId('shiki-code');
    expect(shiki).toBeTruthy();
    expect(shiki.getAttribute('data-language')).toBe('js');
  });

  it('still renders ShikiCodeBlock for unknown language in chat tier', () => {
    const src = '```unknownlang\nsome code\n```';
    render(<Markdown content={src} tier="chat" />);
    // In chat tier, all fenced code goes through ShikiCodeBlock (even unknown lang)
    const shiki = screen.getByTestId('shiki-code');
    expect(shiki).toBeTruthy();
  });

  it('renders plain pre/code for unknown language in minimal tier', () => {
    const src = '```unknownlang\nsome code\n```';
    const { container } = render(<Markdown content={src} tier="minimal" />);
    const pre = container.querySelector('pre');
    expect(pre).toBeTruthy();
    expect(screen.queryByTestId('shiki-code')).toBeNull();
  });
});

describe('Markdown — fenced code blocks (tier=minimal)', () => {
  it('renders plain <pre><code> even for known language', () => {
    const src = '```python\nprint("hi")\n```';
    const { container } = render(<Markdown content={src} tier="minimal" />);
    const pre = container.querySelector('pre');
    expect(pre).toBeTruthy();
    const code = pre!.querySelector('code');
    expect(code).toBeTruthy();
    expect(screen.queryByTestId('shiki-code')).toBeNull();
  });
});

describe('Markdown — plainFences overrides tier', () => {
  it('forces plain pre/code even in chat tier', () => {
    const src = '```js\nstreaming...\n```';
    const { container } = render(<Markdown content={src} tier="chat" plainFences />);
    const pre = container.querySelector('pre');
    expect(pre).toBeTruthy();
    expect(screen.queryByTestId('shiki-code')).toBeNull();
  });
});

describe('Markdown — mermaid blocks', () => {
  it('renders MermaidBlock for ```mermaid in chat tier', () => {
    const src = '```mermaid\ngraph LR\n  A-->B\n```';
    render(<Markdown content={src} tier="chat" />);
    const mermaid = screen.getByTestId('mermaid-block');
    expect(mermaid).toBeTruthy();
    expect(mermaid.textContent).toContain('graph LR');
  });

  it('renders plain pre/code for ```mermaid in minimal tier', () => {
    const src = '```mermaid\ngraph LR\n  A-->B\n```';
    const { container } = render(<Markdown content={src} tier="minimal" />);
    const pre = container.querySelector('pre');
    expect(pre).toBeTruthy();
    expect(screen.queryByTestId('mermaid-block')).toBeNull();
  });
});
