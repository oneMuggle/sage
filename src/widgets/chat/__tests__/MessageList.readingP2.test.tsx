// 对话阅读体验第二轮 C2：回答版本切换回调只交给最后一条消息，流式输出期间不交。
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message as MessageType } from '../../../shared/lib/store';
import { MessageList } from '../MessageList';

vi.mock('../Message', () => ({
  Message: ({
    message,
    onAnswerVersionChange,
  }: {
    message: { id: string };
    onAnswerVersionChange?: () => void;
  }) => (
    <div data-testid={`msg-${message.id}`}>
      {onAnswerVersionChange && <span data-testid={`versions-${message.id}`} />}
    </div>
  ),
}));

vi.mock('../../../features/chat', () => ({
  BtwOverlay: () => null,
}));

const messages: MessageType[] = [
  { id: 'm1', session_id: 's1', role: 'user', content: '问', created_at: 1 },
  { id: 'm2', session_id: 's1', role: 'assistant', content: '第一步', created_at: 2 },
  { id: 'm3', session_id: 's1', role: 'assistant', content: '终稿', created_at: 3 },
];

const renderList = (streamingMessageId?: string) =>
  render(
    <I18nProvider defaultLocale="zh">
      <MessageList
        messages={messages}
        streamingMessageId={streamingMessageId}
        onAnswerVersionChange={vi.fn()}
      />
    </I18nProvider>,
  );

describe('MessageList — answer versions (C2)', () => {
  it('hands the version callback to the last message only', () => {
    renderList();
    expect(screen.getByTestId('versions-m3')).toBeInTheDocument();
    expect(screen.queryByTestId('versions-m2')).toBeNull();
    expect(screen.queryByTestId('versions-m1')).toBeNull();
  });

  it('withholds it while a reply is streaming', () => {
    renderList('m3');
    expect(screen.queryByTestId('versions-m3')).toBeNull();
  });
});
