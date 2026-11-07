import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ConversationMessage } from '../../../../entities/office/officeWorkspaceStore';
import { AiSidebar } from '../AiSidebar';

vi.mock('../../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key, locale: 'zh', setLocale: vi.fn() }),
}));

vi.mock('../../../../entities/office/officeWorkspaceStore', async () => {
  const actual = await vi.importActual<
    typeof import('../../../../entities/office/officeWorkspaceStore')
  >('../../../../entities/office/officeWorkspaceStore');
  return {
    ...actual,
    useOfficeWorkspaceStore: vi.fn((selector: (state: Record<string, unknown>) => unknown) =>
      selector({ activeDocument: null, conversation: [] }),
    ),
  };
});

const makeMessages = (count: number): ConversationMessage[] =>
  Array.from({ length: count }, (_, i) => ({
    id: `msg-${i}`,
    role: 'assistant' as const,
    content: `Hello ${i}`,
    createdAt: Date.now(),
  }));

const defaultProps = {
  activeTab: 'documents' as const,
  messages: makeMessages(0),
  pending: false,
  errorText: null,
  disabled: false,
  onCommand: vi.fn(),
  onApply: vi.fn(),
  onSkip: vi.fn(),
  onClose: vi.fn(),
  floatingBar: null,
};

describe('AiSidebar', () => {
  it('shows empty state when no messages', () => {
    render(<AiSidebar {...defaultProps} />);
    expect(screen.getByText('office.ai.sidebar.empty')).toBeTruthy();
  });

  it('renders one message element per message', () => {
    render(<AiSidebar {...defaultProps} messages={makeMessages(2)} />);
    expect(screen.getByTestId('office-ai-message-msg-0')).toBeTruthy();
    expect(screen.getByTestId('office-ai-message-msg-1')).toBeTruthy();
  });

  it('calls onClose when close button is clicked', () => {
    const onClose = vi.fn();
    render(<AiSidebar {...defaultProps} onClose={onClose} />);
    fireEvent.click(screen.getByTestId('office-ai-sidebar-close'));
    expect(onClose).toHaveBeenCalled();
  });
});
