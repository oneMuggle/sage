/**
 * Welcome → Chat 首条消息透传测试：
 * 新会话页通过 router state 传入的 pendingOptions（附件 / office 引用）
 * 必须走与聊天页相同的 handleSendMessage 路径，并把引用元数据挂到消息上。
 */
import { render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';
import { Chat } from '../Chat';

const sendMessageMock = vi.fn().mockResolvedValue(undefined);

vi.mock('../../features/send-message/useChat', () => ({
  useChat: () => ({
    sendMessage: sendMessageMock,
    isLoading: false,
    error: null,
    clearError: vi.fn(),
    messages: [],
    loadMessages: vi.fn(),
    interrupt: vi.fn(),
    reattachActiveStream: vi.fn(),
    streamingToolCalls: [],
    pendingMessages: [],
    cancelPending: vi.fn(),
    clearPendingForSession: vi.fn(),
  }),
}));

vi.mock('../../features/manage-settings/useSettings', () => ({
  useSettings: () => ({
    settings: {
      endpoints: [],
      modelSelections: {
        chatModel: { endpointId: null, modelId: null },
        visionModel: { endpointId: null, modelId: null },
        embeddingModel: { endpointId: null, modelId: null },
      },
      maxContext: 4096,
      temperature: 0.7,
    },
    isLoading: false,
  }),
}));

vi.mock('../../shared/api/orchRunClient', () => ({
  orchRunClient: { listSessionRuns: vi.fn().mockResolvedValue({ runs: [] }) },
}));

vi.mock('../../shared/api/desktopInvoke', () => ({
  invoke: vi.fn().mockRejectedValue(new Error('not reached')),
}));

vi.mock('../../shared/api/desktopEvent', () => ({
  listen: vi.fn().mockResolvedValue(() => undefined),
}));

vi.mock('../../shared/lib/hooks/useFileUpload', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../shared/lib/hooks/useFileUpload')>();
  return {
    ...actual,
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
  };
});

beforeEach(() => {
  sendMessageMock.mockClear();
  const setState = useStore.setState as unknown as (partial: Record<string, unknown>) => void;
  setState({ currentSessionId: 'session-meta-1', sessions: [], isLoading: false });
});

describe('Chat — Welcome pending composer options', () => {
  it('sends the pending message with office refs and persists display meta', async () => {
    const officeRefs = [{ docId: 'doc-1', docType: 'pdf' as const, filename: 'q3.pdf' }];

    render(
      <I18nProvider defaultLocale="zh">
        <MemoryRouter
          initialEntries={[
            {
              pathname: '/chat',
              state: {
                pendingMessage: '分析 @reports/q3.pdf',
                pendingOptions: { officeRefs },
              },
            },
          ]}
        >
          <Chat />
        </MemoryRouter>
      </I18nProvider>,
    );

    await waitFor(() => expect(sendMessageMock).toHaveBeenCalled());
    const [content, , refs, , opts] = sendMessageMock.mock.calls[0] as [
      string,
      string | undefined,
      typeof officeRefs,
      string | undefined,
      { displayMeta?: unknown },
    ];
    expect(content).toBe('分析 @reports/q3.pdf');
    expect(refs).toEqual(officeRefs);
    expect(opts.displayMeta).toEqual({
      file_refs: [{ path: 'reports/q3.pdf', name: 'q3.pdf' }],
      office_refs: [{ doc_id: 'doc-1', doc_type: 'pdf', filename: 'q3.pdf' }],
    });
  });

  // 2026-10-29 修复: 仅附件、无正文时旧守卫 `pendingMessage &&` 会把消息丢弃,
  // 导致用户拖拽文件后发送得到一个空会话。验证空正文 + 附件仍能触发发送。
  it('sends an attachment-only message even when the text is empty', async () => {
    const attachments = [
      { name: 'data.csv', size: 1024, type: 'text/csv', dataUrl: 'data:text/csv;base64,YQo=' },
    ];

    render(
      <I18nProvider defaultLocale="zh">
        <MemoryRouter
          initialEntries={[
            {
              pathname: '/chat',
              state: {
                pendingMessage: '',
                pendingOptions: { attachments },
              },
            },
          ]}
        >
          <Chat />
        </MemoryRouter>
      </I18nProvider>,
    );

    await waitFor(() => expect(sendMessageMock).toHaveBeenCalled());
    const [content, , , , opts] = sendMessageMock.mock.calls[0] as [
      string,
      string | undefined,
      unknown,
      string | undefined,
      { displayMeta?: unknown },
    ];
    expect(content).toBe('');
    expect(opts.displayMeta).toEqual({
      attachments: [{ name: 'data.csv', size: 1024, type: 'text/csv' }],
    });
  });
});
