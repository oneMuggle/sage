// 对话阅读导航 A5: 引用（mode='append'）追加到草稿且聚焦输入框；
// 编辑重发（缺省 / 'replace'）保持覆盖语义。
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { ChatInput } from '../ChatInput';

vi.mock('../../../shared/lib/hooks/useFileUpload', () => ({
  useFileUpload: () => ({
    files: [],
    images: [],
    addFile: vi.fn(),
    addImage: vi.fn(),
    removeFile: vi.fn(),
    removeImage: vi.fn(),
    clearAll: vi.fn(),
    handleDrop: vi.fn(),
    handleDragOver: vi.fn(),
    isDragOver: false,
  }),
}));

type Injected = { text: string; nonce: number; mode?: 'replace' | 'append' } | null;

function renderInput(injectedDraft: Injected) {
  return (
    <I18nProvider defaultLocale="zh">
      <ChatInput onSend={vi.fn()} injectedDraft={injectedDraft} />
    </I18nProvider>
  );
}

describe('ChatInput — quote injection (A5)', () => {
  it('appends quotes to the typed draft instead of replacing it, and focuses the input', () => {
    const { rerender } = render(renderInput(null));
    const input = screen.getByTestId('chat-input') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: '我的问题' } });

    rerender(renderInput({ text: '> 第一段', nonce: 1, mode: 'append' }));
    expect(input.value).toBe('我的问题\n\n> 第一段\n\n');
    expect(document.activeElement).toBe(input);
    expect(input.selectionStart).toBe(input.value.length);

    rerender(renderInput({ text: '> 第二段', nonce: 2, mode: 'append' }));
    expect(input.value).toBe('我的问题\n\n> 第一段\n\n> 第二段\n\n');
  });

  it('keeps replace semantics for edit-resend injections', () => {
    const { rerender } = render(renderInput(null));
    const input = screen.getByTestId('chat-input') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: '旧草稿' } });

    rerender(renderInput({ text: '改写后的消息', nonce: 3 }));
    expect(input.value).toBe('改写后的消息');
  });
});
