// src/features/chat/__tests__/BtwOverlay.latex.test.tsx
// alpha.36 (Bug #6): /btw 浮层 markdown 公式必须经 KaTeX 渲染。
//
// 根因：之前 BtwOverlay 只挂 remarkGfm + rehypeKatex，缺 remarkMath ——
// KaTeX 找不到 math AST，$E=mc^2$ 整段以纯文本出现。
// 防漂移：与 Message.tsx 同形状的最小回归断言。

import { render, screen } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';

import { useBtwState } from '../../../entities/chat/btwState';
import { BtwOverlay } from '../BtwOverlay';

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        'chat.btw.title': '补充问题',
        'chat.btw.question': '问题',
        'chat.btw.loading': '思考中...',
        'chat.btw.close': '关闭',
      };
      return translations[key] || key;
    },
  }),
}));

const mockClose = vi.fn();
vi.mock('../useBtwCommand', () => ({
  useBtwCommand: () => ({
    open: vi.fn(),
    close: mockClose,
  }),
}));

describe('BtwOverlay LaTeX rendering (alpha.36 Bug #6)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useBtwState.getState().close();
  });

  it('renders inline $E=mc^2$ via KaTeX', () => {
    useBtwState.getState().open('质能方程');
    useBtwState.getState().appendDelta('质能方程 $E=mc^2$ 是物理学基石。');

    const { container } = render(<BtwOverlay />);
    // answer 区已渲染
    expect(screen.getByTestId('btw-answer')).toBeInTheDocument();
    // KaTeX 产出 .katex span —— remarkMath 缺失则不会出现
    expect(container.querySelector('.katex')).not.toBeNull();
    expect(container.textContent).toContain('E=mc^2');
  });

  it('renders block math via KaTeX-display', () => {
    useBtwState.getState().open('求积分');
    useBtwState.getState().appendDelta('块级公式：\n\n$$\n\\int_0^1 x^2\\,dx = \\frac{1}{3}\n$$\n');

    const { container } = render(<BtwOverlay />);
    expect(container.querySelector('.katex-display')).not.toBeNull();
  });

  it('leaves unpaired dollar as plain text', () => {
    useBtwState.getState().open('价格');
    useBtwState.getState().appendDelta('这件东西只要 $5。');

    const { container } = render(<BtwOverlay />);
    // 未配对的 $ 不是公式，remarkMath 原样保留
    expect(container.querySelector('.katex')).toBeNull();
    expect(container.textContent).toContain('$5');
  });
});