import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type {
  ConversationMessage,
  SuggestionCardData,
} from '../../../../entities/office/officeWorkspaceStore';
import { ConversationArea } from '../ConversationArea';

vi.mock('../../../../shared/lib/i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
    locale: 'zh',
    setLocale: vi.fn(),
  }),
}));

function card(id: string, applied: SuggestionCardData['applied']): SuggestionCardData {
  return {
    id,
    paraIndex: 0,
    severity: 'warning',
    originalText: `old-${id}`,
    suggestedText: `new-${id}`,
    applied,
  };
}

function assistantMessage(id: string, attachments: SuggestionCardData[]): ConversationMessage {
  return { id, role: 'assistant', content: 'audit', createdAt: 1, attachments };
}

function renderConversation(messages: ConversationMessage[]) {
  const onApply = vi.fn();
  const onSkip = vi.fn();
  const onApplyAll = vi.fn();
  render(
    <ConversationArea
      messages={messages}
      pending={false}
      onApply={onApply}
      onSkip={onSkip}
      onApplyAll={onApplyAll}
    />,
  );
  return { onApply, onSkip, onApplyAll };
}

describe('ConversationArea', () => {
  it('renders the empty state when there are no messages', () => {
    renderConversation([]);
    expect(screen.getByTestId('office-ai-conversation').textContent).toBe(
      'office.ai.sidebar.empty',
    );
  });

  it('renders apply-all on the latest pending assistant message only', () => {
    const { onApplyAll } = renderConversation([
      assistantMessage('msg-1', [card('a', 'pending')]),
      assistantMessage('msg-2', [card('b', 'pending')]),
    ]);

    // R25: exactly one apply-all button across the whole conversation.
    const buttons = screen.getAllByTestId('office-ai-audit-apply-all');
    expect(buttons).toHaveLength(1);

    buttons[0].click();
    expect(onApplyAll).toHaveBeenCalledTimes(1);
    expect(onApplyAll).toHaveBeenCalledWith('msg-2');
  });

  it('renders apply-all on the only pending assistant message', () => {
    renderConversation([
      assistantMessage('msg-1', [card('a', 'pending')]),
      { id: 'msg-2', role: 'user', content: 'hi', createdAt: 2 },
    ]);

    expect(screen.getAllByTestId('office-ai-audit-apply-all')).toHaveLength(1);
  });

  it('omits apply-all when no assistant message has pending cards', () => {
    renderConversation([
      assistantMessage('msg-1', [card('a', 'applied'), card('b', 'skipped')]),
      assistantMessage('msg-2', [card('c', 'applied')]),
    ]);

    expect(screen.queryByTestId('office-ai-audit-apply-all')).toBeNull();
  });
});
