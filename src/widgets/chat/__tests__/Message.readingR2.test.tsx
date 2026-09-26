// 对话阅读体验第二轮：Message 接线 —— B2 截断提示与「继续生成」、B1 朗读按钮。
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useReadAloudStore } from '../../../features/chat/readAloudStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message as MessageType } from '../../../shared/lib/store';
import { Message } from '../Message';

const assistant = (patch: Partial<MessageType> = {}): MessageType => ({
  id: 'a-1',
  session_id: 's-1',
  role: 'assistant',
  content: '第一段回答。',
  created_at: 1_750_000_000_000,
  ...patch,
});

const withI18n = (ui: React.ReactElement) => <I18nProvider defaultLocale="zh">{ui}</I18nProvider>;

function installSpeech() {
  const speak = vi.fn();
  const cancel = vi.fn();
  vi.stubGlobal('speechSynthesis', { speak, cancel, getVoices: () => [] });
  vi.stubGlobal(
    'SpeechSynthesisUtterance',
    class {
      text: string;
      constructor(text: string) {
        this.text = text;
      }
    },
  );
  return { speak, cancel };
}

afterEach(() => {
  vi.unstubAllGlobals();
  useReadAloudStore.setState({ speakingId: null });
});

describe('Message — truncation notice (B2)', () => {
  it('shows the notice and a continue button on a truncated last reply', () => {
    const onContinue = vi.fn();
    render(
      withI18n(
        <Message message={assistant({ finish_reason: 'length' })} onContinue={onContinue} />,
      ),
    );
    expect(screen.getByTestId('message-truncated')).toHaveTextContent('回答达到长度上限，已被截断');
    fireEvent.click(screen.getByTestId('continue-generating'));
    expect(onContinue).toHaveBeenCalledTimes(1);
  });

  it('omits the button off the last message, and the notice for normal stops or while streaming', () => {
    const { rerender } = render(
      withI18n(<Message message={assistant({ finish_reason: 'max_tokens' })} />),
    );
    expect(screen.getByTestId('message-truncated')).toBeInTheDocument();
    expect(screen.queryByTestId('continue-generating')).toBeNull();

    rerender(
      withI18n(<Message message={assistant({ finish_reason: 'stop' })} onContinue={vi.fn()} />),
    );
    expect(screen.queryByTestId('message-truncated')).toBeNull();

    rerender(
      withI18n(
        <Message
          message={assistant({ finish_reason: 'length' })}
          isStreaming
          onContinue={vi.fn()}
        />,
      ),
    );
    expect(screen.queryByTestId('message-truncated')).toBeNull();
  });
});

describe('Message — read aloud (B1)', () => {
  it('is hidden when speechSynthesis is unavailable', () => {
    render(withI18n(<Message message={assistant()} />));
    expect(screen.queryByTestId('read-aloud-message')).toBeNull();
  });

  it('reads an assistant reply aloud and toggles into a stop button', () => {
    const { speak, cancel } = installSpeech();
    render(withI18n(<Message message={assistant()} />));
    const button = screen.getByTestId('read-aloud-message');
    expect(button).toHaveAttribute('aria-label', '朗读');

    fireEvent.click(button);
    expect(speak).toHaveBeenCalledTimes(1);
    expect(speak.mock.calls[0][0].text).toBe('第一段回答。');
    expect(button).toHaveAttribute('aria-pressed', 'true');
    expect(button).toHaveAttribute('aria-label', '停止朗读');

    fireEvent.click(button);
    expect(cancel).toHaveBeenCalledTimes(2);
    expect(useReadAloudStore.getState().speakingId).toBeNull();
  });

  it('stops reading when the message unmounts', () => {
    const { cancel } = installSpeech();
    const { unmount } = render(withI18n(<Message message={assistant()} />));
    fireEvent.click(screen.getByTestId('read-aloud-message'));
    unmount();
    expect(cancel).toHaveBeenCalledTimes(2);
    expect(useReadAloudStore.getState().speakingId).toBeNull();
  });

  it('is not offered on user messages or while streaming', () => {
    installSpeech();
    const { rerender } = render(withI18n(<Message message={assistant({ role: 'user' })} />));
    expect(screen.queryByTestId('read-aloud-message')).toBeNull();
    rerender(withI18n(<Message message={assistant()} isStreaming />));
    expect(screen.queryByTestId('read-aloud-message')).toBeNull();
  });
});
