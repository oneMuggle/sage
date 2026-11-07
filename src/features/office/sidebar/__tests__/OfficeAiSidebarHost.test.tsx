import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useOfficeWorkspaceStore } from '../../../../entities/office/officeWorkspaceStore';
import { OfficeAiSidebarHost } from '../OfficeAiSidebarHost';

vi.mock('../../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key, locale: 'zh', setLocale: vi.fn() }),
}));

// The real bar only renders when a live DOM Range exists; stub it so the host's
// `initialCommand` lifecycle can be exercised without a browser selection.
vi.mock('../FloatingActionBar', () => ({
  FloatingActionBar: ({ onAction }: { onAction: (kind: string) => void }) => (
    <button type="button" data-testid="floating-chat" onClick={() => onAction('chat')}>
      chat
    </button>
  ),
}));

const doc = {
  id: 'doc-123',
  workspace_path: '/workspace',
  generated_filename: 'test.docx',
  doc_type: 'word',
  original_filename: 'test.docx',
} as never;

const selection = {
  text: '同一段',
  rawContext: '同一段',
  anchorParaIndex: 0,
  focusParaIndex: 0,
};

function renderHost(): void {
  render(
    <OfficeAiSidebarHost
      activeTab="documents"
      onNavigateTab={vi.fn()}
      workspacePath="/workspace"
      rootRef={{ current: document.createElement('div') }}
    />,
  );
}

describe('OfficeAiSidebarHost', () => {
  beforeEach(() => {
    useOfficeWorkspaceStore.setState({
      activeDocument: doc,
      conversation: [],
      sidebarOpen: true,
      selection,
    });
  });

  it('re-prefills the same selection after the sidebar is closed and reopened', () => {
    renderHost();

    fireEvent.click(screen.getByTestId('floating-chat'));
    expect((screen.getByTestId('office-ai-command-input') as HTMLTextAreaElement).value).toBe(
      '同一段',
    );

    fireEvent.click(screen.getByTestId('office-ai-sidebar-close'));
    expect(screen.queryByTestId('office-ai-command-input')).toBeNull();

    fireEvent.click(screen.getByTestId('floating-chat'));
    expect((screen.getByTestId('office-ai-command-input') as HTMLTextAreaElement).value).toBe(
      '同一段',
    );
  });

  it('re-prefills an equal selection while the sidebar stays open', () => {
    renderHost();

    fireEvent.click(screen.getByTestId('floating-chat'));
    const input = screen.getByTestId('office-ai-command-input') as HTMLTextAreaElement;
    expect(input.value).toBe('同一段');

    fireEvent.change(input, { target: { value: 'edited draft' } });
    expect(input.value).toBe('edited draft');

    fireEvent.click(screen.getByTestId('floating-chat'));
    expect(input.value).toBe('同一段');
  });
});
