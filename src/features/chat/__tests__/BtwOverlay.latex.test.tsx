// @vitest-environment jsdom
/**
 * alpha.36 (Bug #6, 2026-10 在 main 上复发): /btw 浮层 markdown 公式必须经 KaTeX 渲染。
 *
 * 根因：BtwOverlay 只挂 rehype-katex 没挂 remark-math —— rehype-katex 只渲染
 * 已有的 math AST，缺 remark-math 时 `$E=mc^2$` 原样保留为纯文本。现在与聊天
 * 共用 widgets/markdown/plugins 的同一套管线。
 */
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { useBtwState } from '../../../entities/chat/btwState';
import { I18nProvider } from '../../../shared/lib/i18n';
import { BtwOverlay } from '../BtwOverlay';

const renderOverlay = () =>
  render(
    <I18nProvider defaultLocale="zh">
      <BtwOverlay />
    </I18nProvider>,
  );

describe('BtwOverlay LaTeX rendering (alpha.36 Bug #6)', () => {
  beforeEach(() => {
    useBtwState.getState().close();
  });

  it('renders inline $E=mc^2$ via KaTeX', () => {
    const state = useBtwState.getState();
    state.open('质能方程');
    state.appendDelta('质能方程 $E=mc^2$ 是物理学基石。');

    const { container } = renderOverlay();
    expect(screen.getByTestId('btw-answer')).toBeInTheDocument();
    // remark-math 缺失时不会产出 .katex span
    expect(container.querySelector('.katex')).not.toBeNull();
    expect(container.textContent).toContain('E=mc^2');
  });

  it('renders block math via KaTeX-display', () => {
    const state = useBtwState.getState();
    state.open('求积分');
    state.appendDelta('块级公式：\n\n$$\n\\int_0^1 x^2\\,dx = \\frac{1}{3}\n$$\n');

    const { container } = renderOverlay();
    expect(container.querySelector('.katex-display')).not.toBeNull();
  });

  it('leaves unpaired dollar as plain text', () => {
    const state = useBtwState.getState();
    state.open('价格');
    state.appendDelta('这件东西只要 $5。');

    const { container } = renderOverlay();
    expect(container.querySelector('.katex')).toBeNull();
    expect(container.textContent).toContain('$5');
  });
});
