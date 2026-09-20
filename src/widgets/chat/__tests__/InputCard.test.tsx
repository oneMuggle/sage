import { render, screen, fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { InputCard } from '../InputCard';

// Mock useI18n
vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
    locale: 'zh',
  }),
}));

describe('InputCard', () => {
  let defaultProps: {
    value: string;
    onChange: ReturnType<typeof vi.fn>;
    onSubmit: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    defaultProps = {
      value: '',
      onChange: vi.fn(),
      onSubmit: vi.fn(),
    };
  });

  it('renders textarea with placeholder', () => {
    render(<InputCard {...defaultProps} placeholder="Type here" />);
    const textarea = screen.getByPlaceholderText('Type here');
    expect(textarea).toBeInTheDocument();
  });

  it('calls onChange when typing', () => {
    render(<InputCard {...defaultProps} />);
    const textarea = screen.getByRole('textbox');
    fireEvent.change(textarea, { target: { value: 'hello' } });
    expect(defaultProps.onChange).toHaveBeenCalledWith('hello');
  });

  it('calls onSubmit on Enter key', () => {
    render(<InputCard {...defaultProps} value="test message" />);
    const textarea = screen.getByRole('textbox');
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });
    expect(defaultProps.onSubmit).toHaveBeenCalledTimes(1);
  });

  it('does not call onSubmit on Shift+Enter', () => {
    render(<InputCard {...defaultProps} value="test message" />);
    const textarea = screen.getByRole('textbox');
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true });
    expect(defaultProps.onSubmit).not.toHaveBeenCalled();
  });

  it('does not call onSubmit when Enter is pressed during IME composition', () => {
    render(<InputCard {...defaultProps} value="正在输入" />);
    const textarea = screen.getByRole('textbox');
    // KeyboardEventInit.isComposing (top-level option) is the W3C-standard
    // signal we read in the handler. Passing it at the top level lets
    // fireEvent construct a real KeyboardEvent with the flag set.
    fireEvent.keyDown(textarea, { key: 'Enter', isComposing: true });
    expect(defaultProps.onSubmit).not.toHaveBeenCalled();
  });

  it('disables textarea when disabled prop is true', () => {
    render(<InputCard {...defaultProps} disabled />);
    const textarea = screen.getByRole('textbox');
    expect(textarea).toBeDisabled();
  });

  it('auto-focuses textarea when autoFocus is true', () => {
    render(<InputCard {...defaultProps} autoFocus />);
    const textarea = screen.getByRole('textbox');
    expect(textarea).toHaveFocus();
  });

  it('shows send button disabled when value is empty', () => {
    render(<InputCard {...defaultProps} />);
    const sendButton = screen.getByRole('button', { name: /chat\.send/i });
    expect(sendButton).toBeDisabled();
  });

  it('shows interrupt button when isLoading is true', () => {
    const onInterrupt = vi.fn();
    render(<InputCard {...defaultProps} isLoading onInterrupt={onInterrupt} />);
    const stopButton = screen.getByRole('button', { name: /chat\.stop/i });
    expect(stopButton).toBeInTheDocument();
    stopButton.click();
    expect(onInterrupt).toHaveBeenCalledTimes(1);
  });

  // U5 (2026-09-18): 运行中发送不再被停止按钮顶掉 —— 否则鼠标用户只剩"停止"
  // 一条路，排队/插话能力等于不存在。
  it('keeps send next to stop while loading so busy sends can queue', () => {
    const onSubmit = vi.fn();
    const onNewTopic = vi.fn();
    render(
      <InputCard
        {...defaultProps}
        value="补充一句"
        onSubmit={onSubmit}
        onNewTopic={onNewTopic}
        isLoading
        onInterrupt={vi.fn()}
      />,
    );
    const sendButton = screen.getByTestId('chat-send');
    expect(sendButton).toBeEnabled();
    sendButton.click();
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: /chat\.stop/i })).toBeInTheDocument();
    expect(screen.queryByTestId('chat-new-topic')).toBeNull();
  });

  // U20: Emacs-style keybindings wired into the textarea.
  // Ctrl+A is intentionally NOT intercepted: native select-all wins.
  it('Ctrl+A passes through (native select-all preserved)', () => {
    render(<InputCard {...defaultProps} value="hello world" />);
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    textarea.setSelectionRange(5, 5);

    const handled = fireEvent.keyDown(textarea, { key: 'a', ctrlKey: true });

    expect(handled).toBe(true); // fireEvent returns true even when not prevented
    // The hook returns false (no preventDefault); selection is untouched.
    expect(textarea.selectionStart).toBe(5);
    expect(textarea.selectionEnd).toBe(5);
    expect(defaultProps.onChange).not.toHaveBeenCalled();
    expect(defaultProps.onSubmit).not.toHaveBeenCalled();
  });

  it('Ctrl+K kills to end of line via onChange', () => {
    render(<InputCard {...defaultProps} value="hello world" />);
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    textarea.setSelectionRange(5, 5);

    fireEvent.keyDown(textarea, { key: 'k', ctrlKey: true });

    expect(defaultProps.onChange).toHaveBeenCalledWith('hello');
    expect(defaultProps.onSubmit).not.toHaveBeenCalled();
  });

  it('Ctrl+Backspace kills the previous word (Windows convention)', () => {
    render(<InputCard {...defaultProps} value="foo bar baz" />);
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    textarea.setSelectionRange(7, 7);

    fireEvent.keyDown(textarea, { key: 'Backspace', ctrlKey: true });

    expect(defaultProps.onChange).toHaveBeenCalledWith('foo  baz');
    expect(defaultProps.onSubmit).not.toHaveBeenCalled();
  });

  it('Emacs bindings are inert when disabled', () => {
    render(<InputCard {...defaultProps} value="hello world" disabled />);
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;

    // jsdom still dispatches keydown to disabled textareas via fireEvent;
    // the hook must ignore it because enabled=false.
    const handled = fireEvent.keyDown(textarea, { key: 'k', ctrlKey: true });

    expect(handled).toBe(true); // default NOT prevented
    expect(defaultProps.onChange).not.toHaveBeenCalled();
  });

  // Autosize: textarea must auto-grow when value spans multiple lines.
  // jsdom does not compute layout, so scrollHeight is not meaningful here.
  // We assert the inline style is updated on value change — the shape that
  // ensures the textarea's height tracks the content visually in a real DOM.
  it('updates textarea height inline style when value changes (autosize)', () => {
    const { rerender } = render(<InputCard {...defaultProps} value="" />);
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;

    // Baseline: empty value still triggers an autosize pass to reset
    // the height to 'auto' before measuring.
    expect(textarea.style.height).not.toBe('');

    rerender(<InputCard {...defaultProps} value={'line1\nline2\nline3\nline4'} />);

    // After multi-line content, autosize must apply an explicit pixel height
    // (capped at 200px). jsdom reports a 0 scrollHeight, so the cap branch
    // is exercised — what we care about is that style.height is set.
    expect(textarea.style.height).toMatch(/^\d+px$/);
  });

  // Char-count footer: surfaces a counter when the value approaches the
  // 4000-char hard limit, switches to red when the limit is exceeded.
  it('hides the char count below the 75% threshold', () => {
    render(<InputCard {...defaultProps} value={'a'.repeat(2000)} />);
    expect(screen.queryByTestId('chat-char-count')).toBeNull();
  });

  it('shows the char count above the 75% threshold (muted)', () => {
    render(<InputCard {...defaultProps} value={'a'.repeat(3500)} />);
    const counter = screen.getByTestId('chat-char-count');
    expect(counter.textContent).toBe('3500 / 4000');
    expect(counter.className).toContain('text-muted');
    expect(counter.className).not.toContain('text-error');
  });

  it('turns the char count red past the hard limit', () => {
    render(<InputCard {...defaultProps} value={'a'.repeat(4500)} />);
    const counter = screen.getByTestId('chat-char-count');
    expect(counter.textContent).toBe('4500 / 4000');
    expect(counter.className).toContain('text-error');
  });
});

// ============================================================================
// RT8 (round7): Esc 中断 —— isLoading 时 Esc 触发 onInterrupt
// ============================================================================

describe('InputCard — Esc interrupts while streaming (RT8)', () => {
  it('calls onInterrupt on Escape while isLoading', () => {
    const onInterrupt = vi.fn();
    render(
      <InputCard
        value="x"
        onChange={vi.fn()}
        onSubmit={vi.fn()}
        isLoading
        onInterrupt={onInterrupt}
      />,
    );
    const textarea = screen.getByRole('textbox');
    fireEvent.keyDown(textarea, { key: 'Escape' });
    expect(onInterrupt).toHaveBeenCalledTimes(1);
  });

  it('does not call onInterrupt on Escape when not loading', () => {
    const onInterrupt = vi.fn();
    render(<InputCard value="x" onChange={vi.fn()} onSubmit={vi.fn()} onInterrupt={onInterrupt} />);
    const textarea = screen.getByRole('textbox');
    fireEvent.keyDown(textarea, { key: 'Escape' });
    expect(onInterrupt).not.toHaveBeenCalled();
  });

  it('still submits on Enter while isLoading', () => {
    const onSubmit = vi.fn();
    render(<InputCard value="x" onChange={vi.fn()} onSubmit={onSubmit} isLoading />);
    const textarea = screen.getByRole('textbox');
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});

// P2-a (2026-09-20): 运行中发送的三条投递通道 —— 分体按钮（鼠标可见）+
// 修饰键（键盘可达），两条入口都必须落到同一个 onSubmitWithMode。
describe('InputCard — delivery channels (P2-a)', () => {
  const busy = () => {
    const onSubmit = vi.fn();
    const onSubmitWithMode = vi.fn();
    render(
      <InputCard
        value="补充一句"
        onChange={vi.fn()}
        onSubmit={onSubmit}
        onSubmitWithMode={onSubmitWithMode}
        isLoading
        onInterrupt={vi.fn()}
      />,
    );
    return { onSubmit, onSubmitWithMode };
  };

  it('renders the split send button only while loading', () => {
    const onSubmit = vi.fn();
    const { rerender } = render(
      <InputCard
        value="补充一句"
        onChange={vi.fn()}
        onSubmit={onSubmit}
        onSubmitWithMode={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('chat-delivery-menu')).toBeNull();
    rerender(
      <InputCard
        value="补充一句"
        onChange={vi.fn()}
        onSubmit={onSubmit}
        onSubmitWithMode={vi.fn()}
        isLoading
      />,
    );
    expect(screen.getByTestId('chat-delivery-menu')).toBeInTheDocument();
    // 停止按钮不能被挤掉（P0 的结论：两条路都要在）
    expect(screen.getByRole('button', { name: /chat\.stop/i })).toBeInTheDocument();
  });

  it('keeps the legacy single send button when no onSubmitWithMode is wired', () => {
    const onSubmit = vi.fn();
    render(<InputCard value="x" onChange={vi.fn()} onSubmit={onSubmit} isLoading />);
    expect(screen.queryByTestId('chat-delivery-menu')).toBeNull();
    expect(screen.getByTestId('chat-send')).toBeEnabled();
  });

  it('main button sends through the default channel (plain onSubmit)', () => {
    const { onSubmit, onSubmitWithMode } = busy();
    fireEvent.click(screen.getByTestId('chat-send'));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmitWithMode).not.toHaveBeenCalled();
  });

  it('menu lists all three channels with their timing hint', async () => {
    busy();
    fireEvent.pointerDown(screen.getByTestId('chat-delivery-menu'), { button: 0 });
    const menu = await screen.findByRole('menu');
    expect(menu).toBeInTheDocument();
    const steerItem = screen.getByTestId('chat-delivery-steer');
    expect(steerItem).toHaveTextContent('chat.delivery_steer');
    expect(steerItem).toHaveTextContent('chat.delivery_steer_hint');
    expect(screen.getByTestId('chat-delivery-queue')).toHaveTextContent('Alt+Enter');
    expect(screen.getByTestId('chat-delivery-interrupt')).toHaveTextContent('Ctrl+Enter');
  });

  it('picking a menu item sends through that channel', async () => {
    const { onSubmitWithMode } = busy();
    fireEvent.pointerDown(screen.getByTestId('chat-delivery-menu'), { button: 0 });
    fireEvent.click(await screen.findByTestId('chat-delivery-queue'));
    expect(onSubmitWithMode).toHaveBeenCalledWith('queue');
  });

  it('Alt+Enter queues, Ctrl/Cmd+Enter interrupt-and-send, plain Enter keeps default', () => {
    const { onSubmit, onSubmitWithMode } = busy();
    const textarea = screen.getByRole('textbox');

    fireEvent.keyDown(textarea, { key: 'Enter', altKey: true });
    expect(onSubmitWithMode).toHaveBeenLastCalledWith('queue');

    fireEvent.keyDown(textarea, { key: 'Enter', ctrlKey: true });
    expect(onSubmitWithMode).toHaveBeenLastCalledWith('interrupt');

    fireEvent.keyDown(textarea, { key: 'Enter', metaKey: true });
    expect(onSubmitWithMode).toHaveBeenCalledTimes(3);
    expect(onSubmitWithMode).toHaveBeenLastCalledWith('interrupt');

    // 无修饰 = 默认通道，仍然走 onSubmit（旧调用方语义不变）
    fireEvent.keyDown(textarea, { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmitWithMode).toHaveBeenCalledTimes(3);
  });

  it('modifier keys do nothing without onSubmitWithMode (falls back to onSubmit)', () => {
    const onSubmit = vi.fn();
    render(<InputCard value="x" onChange={vi.fn()} onSubmit={onSubmit} isLoading />);
    const textarea = screen.getByRole('textbox');
    fireEvent.keyDown(textarea, { key: 'Enter', altKey: true });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});
