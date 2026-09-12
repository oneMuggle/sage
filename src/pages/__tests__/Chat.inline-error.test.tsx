/**
 * R17-D: Chat 顶层错误内联测试
 *
 * 旧实现: error 时整页替换为 ErrorState —— 历史消息与输入框全部消失。
 * 新实现: 消息区下方渲染内联错误条（chat-inline-error），历史与输入框
 * 保持可见可用，"关闭"清除错误继续对话。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const navigateMock = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

const useChatMock = vi.fn();
vi.mock('../../features/send-message/useChat', () => ({
  useChat: () => useChatMock(),
}));

const useSettingsMock = vi.fn();
vi.mock('../../features/manage-settings/useSettings', () => ({
  useSettings: () => useSettingsMock(),
}));

vi.mock('../../shared/api/orchRunClient', () => ({
  orchRunClient: { listSessionRuns: vi.fn().mockResolvedValue({ runs: [] }) },
}));

vi.mock('../../shared/api/desktopInvoke', () => ({
  invoke: vi.fn().mockRejectedValue(new Error('should not reach IPC')),
}));

vi.mock('../../shared/api/desktopEvent', () => ({
  listen: vi.fn().mockResolvedValue(() => undefined),
}));

vi.mock('../../shared/lib/hooks/useFileUpload', () => ({
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

vi.mock('../../features/chat', () => ({
  BtwOverlay: () => null,
  useBtwCommand: () => ({
    open: vi.fn(),
    close: vi.fn(),
    isOpen: false,
    question: '',
    answer: '',
    isLoading: false,
  }),
  useAtFileQuery: () => ({ query: null, startIdx: 0, endIdx: 0 }),
}));

vi.mock('../../widgets/chat/ChatInput', () => ({
  ChatInput: () => <div data-testid="chat-input-mock" />,
  MessageList: () => null,
  ActiveAgentIndicator: () => null,
}));

import { I18nProvider } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';
import { Chat } from '../Chat';

function baseChat(overrides: Record<string, unknown> = {}) {
  return {
    sendMessage: vi.fn(),
    isLoading: false,
    error: null,
    clearError: vi.fn(),
    messages: [],
    loadMessages: vi.fn(),
    interrupt: vi.fn(),
    currentAgentId: null,
    streamingMessageId: null,
    iteration: 0,
    streamingState: null,
    streamingToolCalls: [],
    taskBoard: null,
    clearTaskBoard: vi.fn(),
    ...overrides,
  };
}

function renderChat() {
  return render(
    <MemoryRouter>
      <I18nProvider>
        <Chat />
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe('Chat — R17-D 错误内联', () => {
  beforeEach(() => {
    navigateMock.mockReset();
    useSettingsMock.mockReturnValue({
      settings: {
        endpoints: [
          {
            id: 'ep1',
            baseUrl: 'https://api.example.com',
            apiKey: 'k',
            discoveredModels: [{ id: 'gpt-test' }],
          },
        ],
        modelSelections: {
          chatModel: { endpointId: 'ep1', modelId: 'gpt-test' },
          visionModel: { endpointId: null, modelId: null },
          embeddingModel: { endpointId: null, modelId: null },
        },
        maxContext: 4096,
        temperature: 0.7,
      },
      updateSettings: vi.fn(),
      resetSettings: vi.fn(),
    });
    useStore.setState({ messages: [], currentSessionId: 'session-1', sessions: [] });
  });

  it('error 时渲染内联错误条，历史与输入框保持可见', () => {
    const clearError = vi.fn();
    useChatMock.mockReturnValue(
      baseChat({
        error: '上游服务 502',
        clearError,
        messages: [
          { id: 'u1', session_id: 'session-1', role: 'user', content: '你好', created_at: 1 },
        ],
      }),
    );
    renderChat();
    const banner = screen.getByTestId('chat-inline-error');
    expect(banner).toHaveTextContent('上游服务 502');
    // 历史区与输入框不再被整页替换顶掉 —— 消息文本与输入框都在文档中
    expect(screen.getByText('你好')).toBeInTheDocument();
    expect(screen.getByTestId('chat-input-mock')).toBeInTheDocument();
  });

  it('点击关闭回调 clearError', async () => {
    const clearError = vi.fn();
    useChatMock.mockReturnValue(baseChat({ error: 'boom', clearError }));
    renderChat();
    fireEvent.click(screen.getByTestId('chat-inline-error').querySelector('button')!);
    await waitFor(() => expect(clearError).toHaveBeenCalledTimes(1));
  });

  it('无 error 时不渲染错误条', () => {
    useChatMock.mockReturnValue(baseChat({}));
    renderChat();
    expect(screen.queryByTestId('chat-inline-error')).not.toBeInTheDocument();
  });
});
