import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useOfficeWorkspaceStore } from '../../../../entities/office/officeWorkspaceStore';
import type { OfficeDocumentSummary } from '../../../../shared/api/types';
import { OfficeAiSidebarHost } from '../OfficeAiSidebarHost';

const { runRewrite, runChat, applySuggestion, markSkipped, runAudit, applyAll } = vi.hoisted(
  () => ({
    runRewrite: vi.fn(async () => undefined),
    runChat: vi.fn(async () => undefined),
    applySuggestion: vi.fn(async () => undefined),
    markSkipped: vi.fn(),
    runAudit: vi.fn(async () => undefined),
    applyAll: vi.fn(async () => undefined),
  }),
);

vi.mock('../../../../shared/lib/i18n', () => ({
  useI18n: () => ({
    t: (key: string) => (key === 'office.ai.edit.prefix' ? '把这段改成：' : key),
    locale: 'zh',
    setLocale: vi.fn(),
  }),
}));

// The real bar only renders when a live DOM Range exists; stub it so every
// floating action can be clicked without a browser selection.
vi.mock('../FloatingActionBar', () => ({
  FloatingActionBar: ({ onAction }: { onAction: (kind: string) => void }) => (
    <div>
      {(['rewrite', 'chat', 'edit', 'audit'] as const).map((kind) => (
        <button
          key={kind}
          type="button"
          data-testid={`floating-${kind}`}
          onClick={() => onAction(kind)}
        >
          {kind}
        </button>
      ))}
    </div>
  ),
}));

vi.mock('../useSelectionCapture', () => ({
  useSelectionCapture: vi.fn(),
}));

vi.mock('../useAiCapabilities', () => ({
  nextMessageId: () => 'sys-1',
  useAiCapabilities: () => ({
    pending: false,
    errorText: null,
    runRewrite,
    runChat,
    applySuggestion,
    markSkipped,
  }),
}));

vi.mock('../useAuditSuggestions', () => ({
  useAuditSuggestions: () => ({ running: false, runAudit, applyAll }),
}));

const doc: OfficeDocumentSummary = {
  id: 'doc-123',
  workspace_path: '/workspace',
  generated_filename: 'test.docx',
  doc_type: 'word',
  original_filename: 'test.docx',
  status: 'parsed',
  created_at: 0,
  updated_at: 0,
  metadata: { file_size_bytes: 0 },
  derived_from: null,
  archived_at: null,
};

const selection = {
  text: '同一段',
  rawContext: '同一段',
  anchorParaIndex: 0,
  focusParaIndex: 0,
};

function makeRoot(): HTMLElement {
  const root = document.createElement('div');
  root.innerHTML = '<p data-paragraph-index="0">原始段落</p><p data-paragraph-index="1">第二段</p>';
  return root;
}

function renderHost(): void {
  render(
    <OfficeAiSidebarHost
      activeTab="documents"
      onNavigateTab={vi.fn()}
      rootRef={{ current: makeRoot() }}
    />,
  );
}

function commandInput(): HTMLTextAreaElement {
  return screen.getByTestId('office-ai-command-input') as HTMLTextAreaElement;
}

function submitCommand(value: string): void {
  fireEvent.change(commandInput(), { target: { value } });
  fireEvent.click(screen.getByTestId('office-ai-command-send'));
}

describe('OfficeAiSidebarHost', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
    expect(commandInput().value).toBe('同一段');

    fireEvent.click(screen.getByTestId('office-ai-sidebar-close'));
    expect(screen.queryByTestId('office-ai-command-input')).toBeNull();

    fireEvent.click(screen.getByTestId('floating-chat'));
    expect(commandInput().value).toBe('同一段');
  });

  it('re-prefills an equal selection while the sidebar stays open', () => {
    renderHost();

    fireEvent.click(screen.getByTestId('floating-chat'));
    const input = commandInput();
    expect(input.value).toBe('同一段');

    fireEvent.change(input, { target: { value: 'edited draft' } });
    expect(input.value).toBe('edited draft');

    fireEvent.click(screen.getByTestId('floating-chat'));
    expect(input.value).toBe('同一段');
  });

  it('prefills the edit draft with the i18n prefix and submits a custom rewrite', () => {
    renderHost();

    fireEvent.click(screen.getByTestId('floating-edit'));
    expect(commandInput().value).toBe('把这段改成：同一段');

    submitCommand('把这段改成：改成正式语气');

    expect(runRewrite).toHaveBeenCalledTimes(1);
    expect(runRewrite).toHaveBeenCalledWith({
      instruction: 'custom',
      customInstruction: '改成正式语气',
      text: '原始段落',
      paraIndex: 0,
    });
    expect(runChat).not.toHaveBeenCalled();
  });

  it('routes the /audit command to runAudit', () => {
    renderHost();

    submitCommand('/audit');

    expect(runAudit).toHaveBeenCalledTimes(1);
    expect(runRewrite).not.toHaveBeenCalled();
  });

  it('routes the floating audit action to runAudit and opens the sidebar', () => {
    useOfficeWorkspaceStore.setState({ sidebarOpen: false });
    renderHost();

    expect(screen.queryByTestId('office-ai-command-input')).toBeNull();
    fireEvent.click(screen.getByTestId('floating-audit'));

    expect(runAudit).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('office-ai-command-input')).toBeTruthy();
  });

  it('opens the sidebar and reports no_match when the selection has no paragraph', () => {
    useOfficeWorkspaceStore.setState({
      sidebarOpen: false,
      selection: { ...selection, anchorParaIndex: null },
    });
    renderHost();

    fireEvent.click(screen.getByTestId('floating-edit'));

    expect(screen.getByTestId('office-ai-command-input')).toBeTruthy();
    const messages = useOfficeWorkspaceStore.getState().conversation;
    expect(messages).toHaveLength(1);
    expect(messages[0].content).toBe('office.ai.edit.no_match');
    expect(runRewrite).not.toHaveBeenCalled();
  });

  it('opens the sidebar and reports no_match when the paragraph text is empty', () => {
    useOfficeWorkspaceStore.setState({
      sidebarOpen: false,
      selection: { ...selection, anchorParaIndex: 5 },
    });
    renderHost();

    fireEvent.click(screen.getByTestId('floating-edit'));

    expect(screen.getByTestId('office-ai-command-input')).toBeTruthy();
    const messages = useOfficeWorkspaceStore.getState().conversation;
    expect(messages).toHaveLength(1);
    expect(messages[0].content).toBe('office.ai.edit.no_match');
    expect(runRewrite).not.toHaveBeenCalled();
  });

  it('drops a pending edit when the user submits a chat message instead', () => {
    renderHost();

    fireEvent.click(screen.getByTestId('floating-edit'));
    expect(commandInput().value).toBe('把这段改成：同一段');

    submitCommand('问个问题');

    expect(runChat).toHaveBeenCalledWith('问个问题');
    expect(runRewrite).not.toHaveBeenCalled();
  });

  it('drops a pending edit when the user submits /summarize instead', () => {
    renderHost();

    fireEvent.click(screen.getByTestId('floating-edit'));
    submitCommand('/summarize');

    expect(runRewrite).toHaveBeenCalledTimes(1);
    expect(runRewrite).toHaveBeenCalledWith({
      instruction: 'summarize',
      text: '原始段落\n第二段',
    });
    expect(runRewrite).not.toHaveBeenCalledWith(expect.objectContaining({ instruction: 'custom' }));
  });

  it('drops a pending edit when the user submits /audit instead', () => {
    renderHost();

    fireEvent.click(screen.getByTestId('floating-edit'));
    submitCommand('/audit');

    expect(runAudit).toHaveBeenCalledTimes(1);
    expect(runRewrite).not.toHaveBeenCalled();
  });
});
