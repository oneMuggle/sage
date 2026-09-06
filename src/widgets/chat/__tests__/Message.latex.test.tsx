// src/widgets/chat/__tests__/Message.latex.test.tsx
// U7 (批次 C-2): markdown 中的 LaTeX 数学公式经 KaTeX 渲染。
import { render } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message as MessageType } from '../../../shared/lib/store';
import { Message } from '../Message';

const base: MessageType = {
  id: 'm1',
  session_id: 's1',
  role: 'assistant',
  content: '',
  created_at: 1,
};

function renderMessage(content: string) {
  return render(
    <I18nProvider>
      <Message message={{ ...base, content }} />
    </I18nProvider>,
  );
}

describe('Message LaTeX rendering (U7)', () => {
  it('renders inline math $E=mc^2$ via KaTeX', () => {
    const { container } = renderMessage('质能方程 $E=mc^2$ 是物理学基石。');
    // KaTeX 产出的标记: katex span + annotation 内保留原文
    expect(container.querySelector('.katex')).not.toBeNull();
    expect(container.textContent).toContain('E=mc^2');
  });

  it('renders block math ($$ on own lines) as katex-display', () => {
    const { container } = renderMessage(
      '$$\n\\int_0^1 x^2\\,dx = \\frac{1}{3}\n$$',
    );
    // 块级公式被 KaTeX-display 包裹
    expect(container.querySelector('.katex-display')).not.toBeNull();
  });

  it('leaves unpaired dollar as plain text', () => {
    const { container } = renderMessage('这件东西只要 $5。');
    // 未配对的 $ 不是公式 — remark-math 原样保留
    expect(container.querySelector('.katex')).toBeNull();
    expect(container.textContent).toContain('$5');
  });
});
