/**
 * alpha.36 (Bug #6): wiki MarkdownPreview 的公式必须经 KaTeX 渲染。
 *
 * 根因：早前 MarkdownPreview 完全不挂 KaTeX 插件，`$E=mc^2$` / `$$...$$`
 * 整段以纯文本出现。现在它委托给共享 <Markdown>（widgets/markdown），
 * 插件来自 plugins.ts。本测试从消费端锁住行为。
 *
 * 注意：测试内容用 const 模板字符串而非 JSX 属性字符串字面量——后者
 * 在 remark-math 解析时会把 \n 紧贴 $$ 的边界吃掉，破坏 $$ 独占行的
 * 块级规则（同样边界在运行时渲染没问题，但测试环境对 \n 紧贴 $ 严格）。
 */
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { MarkdownPreview } from '../MarkdownPreview';

describe('MarkdownPreview LaTeX (alpha.36 Bug #6)', () => {
  it('renders inline $E=mc^2$ via KaTeX', () => {
    const content = '质能方程 $E=mc^2$ 是物理学基石。';
    const { container } = render(<MarkdownPreview content={content} />);
    expect(container.querySelector('.katex')).not.toBeNull();
    expect(container.textContent).toContain('E=mc^2');
  });

  it('renders block math via KaTeX-display', () => {
    const content = '$$\n\\int_0^1 x^2\\,dx = \\frac{1}{3}\n$$';
    const { container } = render(<MarkdownPreview content={content} />);
    expect(container.querySelector('.katex-display')).not.toBeNull();
  });

  it('leaves unpaired dollar as plain text', () => {
    const content = '这件东西只要 $5。';
    const { container } = render(<MarkdownPreview content={content} />);
    expect(container.querySelector('.katex')).toBeNull();
    expect(container.textContent).toContain('$5');
  });
});
