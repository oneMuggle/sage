import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { ThinkingPanel } from '../MessageMarkdownParts';

// ThinkingPanel 仅被 Message.tsx 使用，且内部使用字面中文标签 —— 无需 I18nProvider。
// 每个测试使用独一无二的 reasoning 文本，避免模块级 memory Map 跨测试污染。
describe('ThinkingPanel — variant key + streaming auto-expand gating', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it('mode="detail" + isStreaming auto-expands', () => {
    const reasoning = 'A-first-line\nA-second-detail-auto-expand-detail-mode';
    const { container } = render(
      <ThinkingPanel reasoning={reasoning} isStreaming mode="detail" defaultExpanded={false} />,
    );
    const header = screen.getByRole('button', { name: /思考过程/ });
    expect(header).toHaveAttribute('aria-expanded', 'true');
    expect(container.textContent).toContain('A-second-detail-auto-expand-detail-mode');
  });

  it('mode="trace" + isStreaming stays collapsed', () => {
    const reasoning = 'B-first-line\nB-second-detail-trace-should-stay-hidden';
    const { container } = render(
      <ThinkingPanel reasoning={reasoning} isStreaming mode="trace" defaultExpanded={false} />,
    );
    const header = screen.getByRole('button', { name: /思考过程/ });
    expect(header).toHaveAttribute('aria-expanded', 'false');
    expect(container.textContent).not.toContain('B-second-detail-trace-should-stay-hidden');
  });

  it('isolates expansion state per mode and resets on mode switch', () => {
    const reasoning = 'C-first-line\nC-second-detail-variant-switch';
    const { container, rerender } = render(
      <ThinkingPanel reasoning={reasoning} isStreaming mode="detail" defaultExpanded={false} />,
    );
    const detailHeader = screen.getByRole('button', { name: /思考过程/ });
    // detail + streaming → auto-expanded
    expect(detailHeader).toHaveAttribute('aria-expanded', 'true');

    // switch to trace → collapsed (trace has no stored state / no auto-expand)
    rerender(
      <ThinkingPanel reasoning={reasoning} isStreaming mode="trace" defaultExpanded={false} />,
    );
    expect(screen.getByRole('button', { name: /思考过程/ })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    expect(container.textContent).not.toContain('C-second-detail-variant-switch');

    // switch back to detail → memory remembers the detail key → expanded again
    rerender(
      <ThinkingPanel reasoning={reasoning} isStreaming mode="detail" defaultExpanded={false} />,
    );
    expect(screen.getByRole('button', { name: /思考过程/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    expect(container.textContent).toContain('C-second-detail-variant-switch');
  });

  it('preserves explicit user choice across rerenders in the same mode', () => {
    const reasoning = 'D-first-line\nD-second-detail-explicit-choice';
    const { container, rerender } = render(
      <ThinkingPanel
        reasoning={reasoning}
        isStreaming={false}
        mode="trace"
        defaultExpanded={false}
      />,
    );
    // default collapsed
    expect(screen.getByRole('button', { name: /思考过程/ })).toHaveAttribute(
      'aria-expanded',
      'false',
    );

    // user explicitly expands
    fireEvent.click(screen.getByRole('button', { name: /思考过程/ }));
    expect(screen.getByRole('button', { name: /思考过程/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    expect(container.textContent).toContain('D-second-detail-explicit-choice');

    // rerender same mode → explicit choice preserved
    rerender(
      <ThinkingPanel
        reasoning={reasoning}
        isStreaming={false}
        mode="trace"
        defaultExpanded={false}
      />,
    );
    expect(screen.getByRole('button', { name: /思考过程/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    expect(container.textContent).toContain('D-second-detail-explicit-choice');
  });

  it('keeps a user-expanded panel open while streamed reasoning grows (ref-gated reset)', () => {
    const { rerender } = render(<ThinkingPanel reasoning="第一行思考" isStreaming mode="trace" />);
    fireEvent.click(screen.getByRole('button', { name: /思考过程/ }));
    expect(screen.getByRole('button', { name: /思考过程/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );

    // 流式 delta 改变 reasoning 内容 → thinkingExpansionKey 变化；mode 未变，
    // reset effect 必须被 prevModeRef 挡住，不能把用户手动展开的面板折回去。
    rerender(<ThinkingPanel reasoning="第一行思考\n第二行新增" isStreaming mode="trace" />);
    expect(screen.getByRole('button', { name: /思考过程/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
  });
});
