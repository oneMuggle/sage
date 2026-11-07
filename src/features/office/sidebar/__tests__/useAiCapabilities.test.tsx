import { renderHook, act } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { useOfficeWorkspaceStore } from '../../../../entities/office/officeWorkspaceStore';
import { aiApi } from '../../../../shared/api/aiApi';
import * as officeSpecApi from '../../../../shared/api/officeSpecApi';
import { useAiCapabilities } from '../useAiCapabilities';

vi.mock('../../../../shared/api/aiApi');
vi.mock('../../../../shared/api/officeSpecApi', () => ({
  officeSpecApi: {
    reviseAiIssues: vi.fn(),
  },
}));
vi.mock('../../../../shared/lib/i18n', () => ({
  useI18n: () => ({
    t: (key: string, params?: Record<string, string>) => {
      if (params) return `${key}:${JSON.stringify(params)}`;
      return key;
    },
    locale: 'zh',
    setLocale: vi.fn(),
  }),
}));

const mockAiApi = vi.mocked(aiApi);
const mockOfficeSpecApi = vi.mocked(officeSpecApi.officeSpecApi);

function wrapper({ children }: { children: ReactNode }) {
  return <div>{children}</div>;
}

describe('useAiCapabilities', () => {
  let rootRef: { current: HTMLElement | null };

  beforeEach(() => {
    vi.clearAllMocks();
    useOfficeWorkspaceStore.setState({
      activeDocument: null,
      conversation: [],
      selection: null,
    });
    rootRef = { current: document.createElement('div') };
  });

  it('writes a system error when no activeDocument on runRewrite', async () => {
    const { result } = renderHook(
      () =>
        useAiCapabilities({
          rootRef: rootRef as React.RefObject<HTMLElement>,
          filePath: null,
          onNavigateTab: vi.fn(),
        }),
      { wrapper },
    );

    await act(async () => {
      await result.current.runRewrite({
        instruction: 'polish',
        text: 'test',
        paraIndex: 0,
      });
    });

    expect(mockAiApi.rewrite).not.toHaveBeenCalled();
    const messages = useOfficeWorkspaceStore.getState().conversation;
    expect(messages).toHaveLength(1);
    expect(messages[0].role).toBe('system');
    expect(messages[0].content).toBe('office.ai.sidebar.no_document');
  });

  it('calls aiApi.rewrite and appends assistant message with suggestion card', async () => {
    const mockDoc = {
      id: 'doc-123',
      workspace_path: '/workspace',
      generated_filename: 'test.docx',
      doc_type: 'word',
    } as never;

    useOfficeWorkspaceStore.setState({ activeDocument: mockDoc });

    mockAiApi.rewrite.mockResolvedValue({
      ok: true,
      result: 'Rewritten text',
      model: 'test-model',
    });

    const { result } = renderHook(
      () =>
        useAiCapabilities({
          rootRef: rootRef as React.RefObject<HTMLElement>,
          filePath: null,
          onNavigateTab: vi.fn(),
        }),
      { wrapper },
    );

    await act(async () => {
      await result.current.runRewrite({
        instruction: 'polish',
        text: 'original',
        paraIndex: 2,
      });
    });

    expect(mockAiApi.rewrite).toHaveBeenCalledWith({
      workspacePath: '/workspace',
      documentId: 'doc-123',
      text: 'original',
      instruction: 'polish',
    });

    const messages = useOfficeWorkspaceStore.getState().conversation;
    expect(messages).toHaveLength(1);
    expect(messages[0].role).toBe('assistant');
    expect(messages[0].content).toBe('Rewritten text');
    expect(messages[0].attachments).toHaveLength(1);
    expect(messages[0].attachments?.[0].paraIndex).toBe(2);
    expect(messages[0].attachments?.[0].applied).toBe('pending');
  });

  it('appends system message and sets errorText on rewrite failure', async () => {
    const mockDoc = {
      id: 'doc-123',
      workspace_path: '/workspace',
      generated_filename: 'test.docx',
      doc_type: 'word',
    } as never;

    useOfficeWorkspaceStore.setState({ activeDocument: mockDoc });

    mockAiApi.rewrite.mockRejectedValue(new Error('Network error'));

    const { result } = renderHook(
      () =>
        useAiCapabilities({
          rootRef: rootRef as React.RefObject<HTMLElement>,
          filePath: null,
          onNavigateTab: vi.fn(),
        }),
      { wrapper },
    );

    await act(async () => {
      await result.current.runRewrite({
        instruction: 'polish',
        text: 'test',
        paraIndex: 0,
      });
    });

    const messages = useOfficeWorkspaceStore.getState().conversation;
    expect(messages).toHaveLength(1);
    expect(messages[0].role).toBe('system');
    expect(messages[0].content).toContain('office.ai.sidebar.request_failed');
    expect(result.current.errorText).toContain('office.ai.sidebar.request_failed');
  });

  it('builds history from conversation for runChat', async () => {
    const mockDoc = {
      id: 'doc-123',
      workspace_path: '/workspace',
      generated_filename: 'test.docx',
      doc_type: 'word',
    } as never;

    useOfficeWorkspaceStore.setState({
      activeDocument: mockDoc,
      conversation: [
        { id: '1', role: 'user', content: 'Hello', createdAt: 1 },
        { id: '2', role: 'assistant', content: 'Hi there', createdAt: 2 },
        { id: '3', role: 'system', content: 'System msg', createdAt: 3 },
      ],
    });

    mockAiApi.chat.mockResolvedValue({
      ok: true,
      reply: 'Chat reply',
      model: 'test-model',
    });

    const { result } = renderHook(
      () =>
        useAiCapabilities({
          rootRef: rootRef as React.RefObject<HTMLElement>,
          filePath: null,
          onNavigateTab: vi.fn(),
        }),
      { wrapper },
    );

    await act(async () => {
      await result.current.runChat('How are you?');
    });

    expect(mockAiApi.chat).toHaveBeenCalledWith({
      workspacePath: '/workspace',
      documentId: 'doc-123',
      message: 'How are you?',
      history: [
        { role: 'user', content: 'Hello' },
        { role: 'assistant', content: 'Hi there' },
      ],
      documentContext: expect.any(String),
    });

    const messages = useOfficeWorkspaceStore.getState().conversation;
    expect(messages).toHaveLength(5);
    expect(messages[3].role).toBe('user');
    expect(messages[3].content).toBe('How are you?');
    expect(messages[4].role).toBe('assistant');
    expect(messages[4].content).toBe('Chat reply');
  });

  it('rejects applySuggestion without a filePath', async () => {
    const mockDoc = {
      id: 'doc-123',
      workspace_path: '/workspace',
      generated_filename: 'test.docx',
      doc_type: 'word',
    } as never;

    useOfficeWorkspaceStore.setState({ activeDocument: mockDoc });

    const { result } = renderHook(
      () =>
        useAiCapabilities({
          rootRef: rootRef as React.RefObject<HTMLElement>,
          filePath: null,
          onNavigateTab: vi.fn(),
        }),
      { wrapper },
    );

    await act(async () => {
      await result.current.applySuggestion('msg-1', {
        id: 'sg-1',
        paraIndex: 0,
        severity: 'info',
        originalText: 'old',
        suggestedText: 'new',
        applied: 'pending',
      });
    });

    expect(mockOfficeSpecApi.reviseAiIssues).not.toHaveBeenCalled();
    const messages = useOfficeWorkspaceStore.getState().conversation;
    expect(messages).toHaveLength(1);
    expect(messages[0].role).toBe('system');
    expect(messages[0].content).toBe('office.ai.sidebar.apply_disabled');
  });

  it('applies a suggestion and marks it applied (R11: doc_id is activeDocument.id)', async () => {
    const mockDoc = {
      id: 'doc-123',
      workspace_path: '/workspace',
      generated_filename: 'test.docx',
      doc_type: 'word',
    } as never;

    const suggestion = {
      id: 'sg-1',
      paraIndex: 0,
      severity: 'info' as const,
      originalText: 'old',
      suggestedText: 'new',
      applied: 'pending' as const,
    };

    useOfficeWorkspaceStore.setState({
      activeDocument: mockDoc,
      conversation: [
        {
          id: 'msg-1',
          role: 'assistant',
          content: 'new',
          attachments: [suggestion],
          createdAt: 1,
        },
      ],
    });

    mockOfficeSpecApi.reviseAiIssues.mockResolvedValue({
      ok: true,
      doc_id: 'doc-123',
      snapshot_path: null,
      source_path: '/workspace/test.docx',
      output_path: '/workspace/test.docx',
      overwritten: true,
      planned: 1,
      applied: 1,
      skipped: [],
    } as never);

    const { result } = renderHook(
      () =>
        useAiCapabilities({
          rootRef: rootRef as React.RefObject<HTMLElement>,
          filePath: '/workspace/test.docx',
          onNavigateTab: vi.fn(),
        }),
      { wrapper },
    );

    await act(async () => {
      await result.current.applySuggestion('msg-1', suggestion);
    });

    expect(mockOfficeSpecApi.reviseAiIssues).toHaveBeenCalledWith(
      expect.objectContaining({
        workspace_path: '/workspace',
        file_path: '/workspace/test.docx',
        doc_id: 'doc-123',
        add_comments: true,
      }),
    );

    const messages = useOfficeWorkspaceStore.getState().conversation;
    expect(messages[0].attachments?.[0].applied).toBe('applied');
    expect(messages[1].role).toBe('system');
    expect(messages[1].content).toBe('office.ai.sidebar.apply_done');
  });
});
