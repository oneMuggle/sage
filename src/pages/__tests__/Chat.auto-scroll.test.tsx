/**
 * Chat 页 自动滚动到底 测试
 *
 * 覆盖 Chat.tsx 中：
 *   - 滚动容器 `<div className="flex-1 overflow-y-auto">` 上挂的 scrollRef
 *   - useEffect 在 messages.length 或最后一条消息 content 变化时,
 *     把 el.scrollTop 设为 el.scrollHeight (跟随新消息/流式 token)
 *
 * 回归: "内容超出 UI 范围后没有滚动条浏览 + 之前的会话没顶上去"
 * (PR-7)
 *
 * 不发起任何真实 IPC/localStorage;useSettings 与 useChat 都被 mock。
 */
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const navigateMock = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

const useSettingsMock = vi.fn();
vi.mock('../../features/manage-settings/useSettings', () => ({
  useSettings: () => useSettingsMock(),
}));

const useChatMock = vi.fn();
vi.mock('../../features/send-message/useChat', () => ({
  useChat: () => useChatMock(),
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
  useAtFileQuery: () => ({
    query: null,
    startIdx: 0,
    endIdx: 0,
  }),
}));

import { I18nProvider } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';
import { Chat } from '../Chat';

const baseMsg = (id: string, role: 'user' | 'assistant', content: string) => ({
  id,
  session_id: 's1',
  role,
  content,
  created_at: 0,
});

describe('Chat — auto-scroll to bottom on new message', () => {
  beforeEach(() => {
    useSettingsMock.mockReturnValue({
      settings: {
        endpoints: [
          {
            id: 'ep-1',
            name: 'Test',
            baseUrl: 'https://api.example.test/v1',
            apiKey: 'sk-test',
            discoveredModels: [],
            lastDiscoveredAt: null,
          },
        ],
        modelSelections: {
          chatModel: { endpointId: 'ep-1', modelId: 'gpt-test' },
          visionModel: { endpointId: null, modelId: null },
          embeddingModel: { endpointId: null, modelId: null },
        },
        maxContext: 4096,
        temperature: 0.7,
      },
      updateSettings: vi.fn(),
      resetSettings: vi.fn(),
    });
    useStore.setState({ messages: [], currentSessionId: null, sessions: [] });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('scrolls to bottom when a new message is added', () => {
    // jsdom 中 scrollHeight 默认 0 — 我们把它设成非零以便断言 scrollTop 被赋值
    const messagesV1 = [baseMsg('1', 'user', 'hello')];

    useChatMock.mockReturnValue({
      messages: messagesV1,
      isLoading: false,
      error: null,
      clearError: vi.fn(),
      sendMessage: vi.fn(),
      interrupt: vi.fn(),
      loadMessages: vi.fn(),
    });

    const { container, rerender } = render(
      <MemoryRouter>
        <I18nProvider>
          <Chat />
        </I18nProvider>
      </MemoryRouter>,
    );
    const scrollEl = container.querySelector('.overflow-y-auto') as HTMLDivElement;
    expect(scrollEl).toBeTruthy();

    // 模拟非零 scrollHeight
    Object.defineProperty(scrollEl, 'scrollHeight', {
      configurable: true,
      get: () => 1234,
    });
    Object.defineProperty(scrollEl, 'clientHeight', {
      configurable: true,
      get: () => 500,
    });

    // 再 push 一条消息 — 触发 re-render + useEffect
    const messagesV2 = [...messagesV1, baseMsg('2', 'assistant', 'world')];
    useChatMock.mockReturnValue({
      messages: messagesV2,
      isLoading: false,
      error: null,
      clearError: vi.fn(),
      sendMessage: vi.fn(),
      interrupt: vi.fn(),
      loadMessages: vi.fn(),
    });

    rerender(
      <MemoryRouter>
        <I18nProvider>
          <Chat />
        </I18nProvider>
      </MemoryRouter>,
    );

    expect(scrollEl.scrollTop).toBe(1234);
  });

  it('scrolls to bottom on streaming content_delta (same length, mutated content)', () => {
    // 流式: messages.length 不变,但最后一条 assistant 的 content 增长。
    // 依赖里同时监听了 lastMsg?.content,保证这种情况也触发滚动。
    const baseAssistant = baseMsg('1', 'assistant', 'hel');
    useChatMock.mockReturnValue({
      messages: [baseAssistant],
      isLoading: true,
      error: null,
      clearError: vi.fn(),
      sendMessage: vi.fn(),
      interrupt: vi.fn(),
      loadMessages: vi.fn(),
    });

    const { container, rerender } = render(
      <MemoryRouter>
        <I18nProvider>
          <Chat />
        </I18nProvider>
      </MemoryRouter>,
    );
    const scrollEl = container.querySelector('.overflow-y-auto') as HTMLDivElement;

    Object.defineProperty(scrollEl, 'scrollHeight', {
      configurable: true,
      get: () => 777,
    });
    Object.defineProperty(scrollEl, 'clientHeight', {
      configurable: true,
      get: () => 300,
    });

    // length 不变,content 从 'hel' → 'hello world'
    useChatMock.mockReturnValue({
      messages: [{ ...baseAssistant, content: 'hello world' }],
      isLoading: true,
      error: null,
      clearError: vi.fn(),
      sendMessage: vi.fn(),
      interrupt: vi.fn(),
      loadMessages: vi.fn(),
    });

    rerender(
      <MemoryRouter>
        <I18nProvider>
          <Chat />
        </I18nProvider>
      </MemoryRouter>,
    );

    expect(scrollEl.scrollTop).toBe(777);
  });
});
