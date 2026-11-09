import { act, renderHook } from '@testing-library/react';
import type { RefObject } from 'react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useOfficeWorkspaceStore } from '../../../../entities/office/officeWorkspaceStore';
import { aiApi } from '../../../../shared/api/aiApi';
import * as officeSpecApi from '../../../../shared/api/officeSpecApi';
import type { AiReviseResult } from '../../../../shared/api/officeSpecTypes';
import type { OfficeDocumentSummary } from '../../../../shared/api/types';
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

vi.mock('sonner', () => ({
  toast: {
    warning: vi.fn(),
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const mockToastWarning = vi.mocked(toast.warning);

const mockAiApi = vi.mocked(aiApi);
const mockOfficeSpecApi = vi.mocked(officeSpecApi.officeSpecApi);

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

function reviseResult(): AiReviseResult {
  return {
    ok: true,
    doc_id: 'doc-123',
    snapshot_path: null,
    source_path: '/workspace/test.docx',
    output_path: '/workspace/test.docx',
    overwritten: true,
    planned: 1,
    applied: 1,
    skipped: 0,
    changes: [
      {
        rule_id: null,
        find: 'old',
        replace: 'new',
        comment: '',
        applied: true,
        reason: '',
      },
    ],
    warnings: [],
  };
}

function makeRoot(html = ''): RefObject<HTMLElement> {
  const root = document.createElement('div');
  root.innerHTML = html;
  return { current: root };
}

function renderCapabilities(rootRef: RefObject<HTMLElement>) {
  return renderHook(() => useAiCapabilities({ rootRef }));
}

describe('useAiCapabilities', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useOfficeWorkspaceStore.setState({
      activeDocument: null,
      conversation: [],
      selection: null,
    });
  });

  it('warns via toast when no activeDocument on runRewrite', async () => {
    const { result } = renderCapabilities(makeRoot());

    await act(async () => {
      await result.current.runRewrite({ instruction: 'polish', text: 'test', paraIndex: 0 });
    });

    expect(mockAiApi.rewrite).not.toHaveBeenCalled();
    // A missing document is transient UI state — it must not enter the
    // conversation history as a system turn.
    expect(mockToastWarning).toHaveBeenCalledWith('office.ai.quick.need_document');
    expect(useOfficeWorkspaceStore.getState().conversation).toHaveLength(0);
  });

  it('warns via toast when no activeDocument on runChat', async () => {
    const { result } = renderCapabilities(makeRoot());

    await act(async () => {
      await result.current.runChat('hello');
    });

    expect(mockAiApi.chat).not.toHaveBeenCalled();
    expect(mockToastWarning).toHaveBeenCalledWith('office.ai.quick.need_document');
    expect(useOfficeWorkspaceStore.getState().conversation).toHaveLength(0);
  });

  it('calls aiApi.rewrite and appends an assistant message with a suggestion card', async () => {
    useOfficeWorkspaceStore.setState({ activeDocument: doc });
    mockAiApi.rewrite.mockResolvedValue({
      ok: true,
      result: 'Rewritten text',
      model: 'test-model',
    });

    const { result } = renderCapabilities(makeRoot());

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

  it('does not attach a suggestion for whole-document rewrites', async () => {
    useOfficeWorkspaceStore.setState({ activeDocument: doc });
    mockAiApi.rewrite.mockResolvedValue({ ok: true, result: 'Summary', model: 'test-model' });

    const { result } = renderCapabilities(makeRoot());

    await act(async () => {
      await result.current.runRewrite({ instruction: 'summarize', text: 'Full text' });
    });

    expect(mockAiApi.rewrite).toHaveBeenCalledWith({
      workspacePath: '/workspace',
      documentId: 'doc-123',
      text: 'Full text',
      instruction: 'summarize',
    });
    const messages = useOfficeWorkspaceStore.getState().conversation;
    expect(messages).toHaveLength(1);
    expect(messages[0].attachments).toHaveLength(0);
  });

  it('forwards customInstruction to aiApi.rewrite for instruction-based edits', async () => {
    useOfficeWorkspaceStore.setState({ activeDocument: doc });
    mockAiApi.rewrite.mockResolvedValue({ ok: true, result: 'Formal text', model: 'test-model' });

    const { result } = renderCapabilities(makeRoot());

    await act(async () => {
      await result.current.runRewrite({
        instruction: 'custom',
        customInstruction: '改成正式语气',
        text: '原始段落',
        paraIndex: 0,
      });
    });

    expect(mockAiApi.rewrite).toHaveBeenCalledWith({
      workspacePath: '/workspace',
      documentId: 'doc-123',
      text: '原始段落',
      instruction: 'custom',
      customInstruction: '改成正式语气',
    });
  });

  it('appends a system message and sets errorText on rewrite failure', async () => {
    useOfficeWorkspaceStore.setState({ activeDocument: doc });
    mockAiApi.rewrite.mockRejectedValue(new Error('Network error'));

    const { result } = renderCapabilities(makeRoot());

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

  it('builds history from conversation and sends joined document paragraphs', async () => {
    useOfficeWorkspaceStore.setState({
      activeDocument: doc,
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

    const rootRef = makeRoot(
      '<p data-paragraph-index="0">第一段</p><p data-paragraph-index="1">第二段</p>',
    );
    const { result } = renderCapabilities(rootRef);

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
      documentContext: '第一段\n第二段',
    });

    const messages = useOfficeWorkspaceStore.getState().conversation;
    expect(messages).toHaveLength(5);
    expect(messages[3].role).toBe('user');
    expect(messages[3].content).toBe('How are you?');
    expect(messages[4].role).toBe('assistant');
    expect(messages[4].content).toBe('Chat reply');
  });

  it('caps chat history at the last 20 non-system messages', async () => {
    const seeded = Array.from({ length: 25 }, (_, index) => ({
      id: `m-${index}`,
      role: index % 2 === 0 ? ('user' as const) : ('assistant' as const),
      content: `message-${index}`,
      createdAt: index,
    }));

    useOfficeWorkspaceStore.setState({ activeDocument: doc, conversation: seeded });
    mockAiApi.chat.mockResolvedValue({ ok: true, reply: 'ok', model: 'test-model' });

    const { result } = renderCapabilities(makeRoot());

    await act(async () => {
      await result.current.runChat('next');
    });

    const call = mockAiApi.chat.mock.calls[0][0];
    expect(call.history).toHaveLength(20);
    expect(call.history).toEqual(seeded.slice(-20).map(({ role, content }) => ({ role, content })));
  });

  it('rejects applySuggestion without an active document', async () => {
    const { result } = renderCapabilities(makeRoot());

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

  it('derives file_path from the active document and marks the card applied', async () => {
    const suggestion = {
      id: 'sg-1',
      paraIndex: 0,
      severity: 'info' as const,
      originalText: 'old',
      suggestedText: 'new',
      applied: 'pending' as const,
    };

    useOfficeWorkspaceStore.setState({
      activeDocument: doc,
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

    mockOfficeSpecApi.reviseAiIssues.mockResolvedValue(reviseResult());

    const { result } = renderCapabilities(makeRoot());

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

    const call = mockOfficeSpecApi.reviseAiIssues.mock.calls[0][0];
    expect(call.issues[0].message).toBe('office.ai.revise.default_message');

    const messages = useOfficeWorkspaceStore.getState().conversation;
    expect(messages[0].attachments?.[0].applied).toBe('applied');
    expect(messages[1].role).toBe('system');
    expect(messages[1].content).toBe('office.ai.sidebar.apply_done');
  });
});
