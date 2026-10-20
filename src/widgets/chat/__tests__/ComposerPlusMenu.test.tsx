/**
 * UX-IA R1 批次 C：输入框「+」工具菜单。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import {
  formatComposerPlusMenuJson,
  formatComposerPlusMenuMarkdown,
} from '../ComposerPlusMenu';
import { InputCard } from '../InputCard';

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key, locale: 'zh' }),
}));

function renderCard(props: Partial<React.ComponentProps<typeof InputCard>> = {}) {
  const onChange = vi.fn();
  const utils = render(
    <InputCard value="" onChange={onChange} onSubmit={vi.fn()} {...props} />,
  );
  return { onChange, ...utils };
}

describe('ComposerPlusMenu (via InputCard)', () => {
  it('is closed by default and opens / closes via the + button', () => {
    renderCard();
    const plus = screen.getByTestId('composer-plus');
    expect(plus).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByTestId('composer-plus-menu')).toBeNull();
    fireEvent.click(plus);
    expect(screen.getByTestId('composer-plus-menu')).toBeInTheDocument();
    fireEvent.click(plus);
    expect(screen.queryByTestId('composer-plus-menu')).toBeNull();
  });

  it('closes on Escape and on outside click', () => {
    renderCard();
    fireEvent.click(screen.getByTestId('composer-plus'));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByTestId('composer-plus-menu')).toBeNull();
    fireEvent.click(screen.getByTestId('composer-plus'));
    fireEvent.mouseDown(document.body);
    expect(screen.queryByTestId('composer-plus-menu')).toBeNull();
  });

  it('only lists items whose handlers are provided', () => {
    renderCard();
    fireEvent.click(screen.getByTestId('composer-plus'));
    expect(screen.queryByTestId('composer-plus-item-image')).toBeNull();
    expect(screen.queryByTestId('composer-plus-item-knowledge')).toBeNull();
    expect(screen.queryByTestId('composer-plus-item-schedule')).toBeNull();
    expect(screen.getByTestId('composer-plus-item-mention')).toBeInTheDocument();
    expect(screen.getByTestId('composer-plus-item-command')).toBeInTheDocument();
  });

  it('knowledge / schedule items call their handlers and close the menu', () => {
    const onToggleKnowledgeSelector = vi.fn();
    const onSchedule = vi.fn();
    renderCard({ onToggleKnowledgeSelector, onSchedule });
    fireEvent.click(screen.getByTestId('composer-plus'));
    fireEvent.click(screen.getByTestId('composer-plus-item-knowledge'));
    expect(onToggleKnowledgeSelector).toHaveBeenCalledWith(true);
    expect(screen.queryByTestId('composer-plus-menu')).toBeNull();
    fireEvent.click(screen.getByTestId('composer-plus'));
    fireEvent.click(screen.getByTestId('composer-plus-item-schedule'));
    expect(onSchedule).toHaveBeenCalledTimes(1);
  });

  it('image item clicks the hidden image input', () => {
    renderCard({ onImageSelect: vi.fn(), onFileSelect: vi.fn() });
    const input = document.getElementById('chat-input-image') as HTMLInputElement;
    const clickSpy = vi.spyOn(input, 'click');
    fireEvent.click(screen.getByTestId('composer-plus'));
    fireEvent.click(screen.getByTestId('composer-plus-item-image'));
    expect(clickSpy).toHaveBeenCalledTimes(1);
  });

  it('mention item appends "@" (with a separating space when needed)', () => {
    const { onChange } = renderCard({ value: 'hello' });
    fireEvent.click(screen.getByTestId('composer-plus'));
    fireEvent.click(screen.getByTestId('composer-plus-item-mention'));
    expect(onChange).toHaveBeenCalledWith('hello @');
  });

  it('command item writes "/" only when the input is empty', () => {
    const { onChange, rerender } = renderCard();
    fireEvent.click(screen.getByTestId('composer-plus'));
    fireEvent.click(screen.getByTestId('composer-plus-item-command'));
    expect(onChange).toHaveBeenCalledWith('/');

    rerender(<InputCard value="draft" onChange={onChange} onSubmit={vi.fn()} />);
    fireEvent.click(screen.getByTestId('composer-plus'));
    expect(screen.getByTestId('composer-plus-item-command')).toBeDisabled();
  });

  it('is disabled together with the input', () => {
    renderCard({ disabled: true });
    expect(screen.getByTestId('composer-plus')).toBeDisabled();
  });

  it('formats and copies composer plus menu items as Markdown and JSON', () => {
    const md = formatComposerPlusMenuMarkdown([
      { key: 'mention', label: '提及文件', hint: '@' },
      { key: 'command', label: '斜杠命令', hint: '/', disabled: true },
    ]);
    expect(md).toContain('# 输入框 + 工具菜单清单 (Composer Plus Menu Summary)');
    expect(md).toContain('提及文件');
    expect(formatComposerPlusMenuMarkdown([])).toContain('_暂无可用工具项_');

    const parsed = JSON.parse(
      formatComposerPlusMenuJson([{ key: 'mention', label: '提及文件', hint: '@' }]),
    );
    expect(parsed.count).toBe(1);

    renderCard();
    fireEvent.click(screen.getByTestId('composer-plus'));
    fireEvent.click(screen.getByTestId('composer-plus-copy-md'));
    expect(screen.getByTestId('composer-plus-copy-md').textContent).toContain('已复制 MD');
    fireEvent.click(screen.getByTestId('composer-plus-copy-json'));
    expect(screen.getByTestId('composer-plus-copy-json').textContent).toContain('已复制 JSON');
  });
});
