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
 * Task 2 (Win7 parity) 起新增 sticky-bottom UX:
 *   - 只在用户**之前**在底部时跟随新消息
 *   - 用户离开底部后不再强制跳到 scrollHeight
 *   - 离开底部 + 流式进行中显示"跳到最新"按钮(aria-label="跳到最新")
 *   - 发送新消息时强制一次 scroll 到底
 *
 * 不发起任何真实 IPC/localStorage;useSettings 与 useChat 都被 mock。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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

// C3 (2026-08-15): Chat → ProgressSection → PlanCardList 渲染链挂载即调
// orchRunClient.listRuns();mock 掉避免真实 IPC 抛错 (unhandled rejection)。
vi.mock('../../shared/api/orchRunClient', () => ({
  orchRunClient: { listRuns: vi.fn().mockResolvedValue([]) },
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
      streamingToolCalls: [],
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
      streamingToolCalls: [],
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
      streamingToolCalls: [],
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
      streamingToolCalls: [],
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

// ============================================================
// Task 2: Sticky-bottom streaming UX
// ============================================================
//
// Behaviour pins (from brief + task contract):
//   - BOTTOM_THRESHOLD_PX = 48 (constant in Chat.tsx)
//   - wasAtBottomRef tracks whether scroll position is within threshold
//   - Only auto-scroll if wasAtBottom was true before the update
//   - When user scrolls away from bottom during stream → show
//     "跳到最新" button (aria-label), don't yank focus
//   - On sending new message → force one explicit scroll to bottom
//     regardless of prior state

describe('Chat — sticky-bottom streaming UX (Task 2)', () => {
  // 滚动容器定位 hook:``container.querySelector('.overflow-y-auto')`` 拿到
  // 真实 DOM。每个测试都给 scrollEl 设 scrollHeight/clientHeight/scrollTop,
  // 让 ``el.scrollHeight - el.clientHeight - el.scrollTop <= 48`` 决定
  // wasAtBottom 状态。
  function setupScrollEl(container: HTMLElement, scrollHeight: number, clientHeight: number, scrollTop: number) {
    const scrollEl = container.querySelector('.overflow-y-auto') as HTMLDivElement;
    Object.defineProperty(scrollEl, 'scrollHeight', { configurable: true, get: () => scrollHeight });
    Object.defineProperty(scrollEl, 'clientHeight', { configurable: true, get: () => clientHeight });
    scrollEl.scrollTop = scrollTop;
    return scrollEl;
  }

  it('does not take focus from history while a token arrives (user scrolled up)', async () => {
    // 模拟用户上滚读历史(scrollTop 120, 内容延伸到 1000)
    const messagesV1 = [baseMsg('1', 'assistant', 'hello')];
    useChatMock.mockReturnValue({
      messages: messagesV1,
      isLoading: true,
      streamingMessageId: '1',
      error: null,
      clearError: vi.fn(),
      sendMessage: vi.fn(),
      interrupt: vi.fn(),
      loadMessages: vi.fn(),
      streamingToolCalls: [],
    });

    const { container, rerender } = render(
      <MemoryRouter>
        <I18nProvider>
          <Chat />
        </I18nProvider>
      </MemoryRouter>,
    );

    const scrollEl = setupScrollEl(container, /* scrollHeight */ 1000, /* clientHeight */ 400, /* scrollTop */ 120);
    // 触发 scroll 事件让 wasAtBottomRef 算一次:
    // 1000 - 400 - 120 = 480 > 48 → 不在底部
    fireEvent.scroll(scrollEl);

    // 新 token 流入(messages 长度不变, content 增长)
    const messagesV2 = [{ ...messagesV1[0], content: 'hello next token' }];
    useChatMock.mockReturnValue({
      messages: messagesV2,
      isLoading: true,
      streamingMessageId: '1',
      error: null,
      clearError: vi.fn(),
      sendMessage: vi.fn(),
      interrupt: vi.fn(),
      loadMessages: vi.fn(),
      streamingToolCalls: [],
    });
    rerender(
      <MemoryRouter>
        <I18nProvider>
          <Chat />
        </I18nProvider>
      </MemoryRouter>,
    );

    // 用户在历史里 → 不能强制 scrollTop=scrollHeight,要保持 120
    await waitFor(() => {
      expect(scrollEl.scrollTop).toBe(120);
    });
  });

  it('follows bottom when user was at bottom before update', async () => {
    // scrollHeight=952, clientHeight=400, scrollTop=552 → 0 距离底部(在阈值内)
    const messagesV1 = [baseMsg('1', 'assistant', 'hel')];
    useChatMock.mockReturnValue({
      messages: messagesV1,
      isLoading: true,
      streamingMessageId: '1',
      error: null,
      clearError: vi.fn(),
      sendMessage: vi.fn(),
      interrupt: vi.fn(),
      loadMessages: vi.fn(),
      streamingToolCalls: [],
    });

    const { container, rerender } = render(
      <MemoryRouter>
        <I18nProvider>
          <Chat />
        </I18nProvider>
      </MemoryRouter>,
    );

    const scrollEl = setupScrollEl(container, /* scrollHeight */ 952, /* clientHeight */ 400, /* scrollTop */ 552);
    fireEvent.scroll(scrollEl); // wasAtBottom=true

    // 流式 token 流入
    const messagesV2 = [{ ...messagesV1[0], content: 'hello world' }];
    useChatMock.mockReturnValue({
      messages: messagesV2,
      isLoading: true,
      streamingMessageId: '1',
      error: null,
      clearError: vi.fn(),
      sendMessage: vi.fn(),
      interrupt: vi.fn(),
      loadMessages: vi.fn(),
      streamingToolCalls: [],
    });
    rerender(
      <MemoryRouter>
        <I18nProvider>
          <Chat />
        </I18nProvider>
      </MemoryRouter>,
    );

    // wasAtBottom=true → 自动滚到 scrollHeight
    await waitFor(() => {
      expect(scrollEl.scrollTop).toBe(scrollEl.scrollHeight);
    });
  });

  it('shows "跳到最新" button when user scrolls up during stream', async () => {
    const messagesV1 = [baseMsg('1', 'assistant', 'hel')];
    useChatMock.mockReturnValue({
      messages: messagesV1,
      isLoading: true,
      streamingMessageId: '1',
      error: null,
      clearError: vi.fn(),
      sendMessage: vi.fn(),
      interrupt: vi.fn(),
      loadMessages: vi.fn(),
      streamingToolCalls: [],
    });

    const { container, rerender } = render(
      <MemoryRouter>
        <I18nProvider>
          <Chat />
        </I18nProvider>
      </MemoryRouter>,
    );

    const scrollEl = setupScrollEl(container, /* scrollHeight */ 1000, /* clientHeight */ 400, /* scrollTop */ 200);
    fireEvent.scroll(scrollEl); // 不在底部

    const messagesV2 = [{ ...messagesV1[0], content: 'hello world' }];
    useChatMock.mockReturnValue({
      messages: messagesV2,
      isLoading: true,
      streamingMessageId: '1',
      error: null,
      clearError: vi.fn(),
      sendMessage: vi.fn(),
      interrupt: vi.fn(),
      loadMessages: vi.fn(),
      streamingToolCalls: [],
    });
    rerender(
      <MemoryRouter>
        <I18nProvider>
          <Chat />
        </I18nProvider>
      </MemoryRouter>,
    );

    // "跳到最新" 按钮存在且 a11y 标签正确
    const jumpBtn = await waitFor(() =>
      screen.getByRole('button', { name: '跳到最新' }),
    );
    expect(jumpBtn).toBeTruthy();
  });

  it('jumps to the latest message and hides the button when clicked', async () => {
    const messages = [baseMsg('1', 'assistant', 'hello')];
    useChatMock.mockReturnValue({
      messages,
      isLoading: true,
      streamingMessageId: '1',
      error: null,
      clearError: vi.fn(),
      sendMessage: vi.fn(),
      interrupt: vi.fn(),
      loadMessages: vi.fn(),
      streamingToolCalls: [],
    });

    const { container } = render(
      <MemoryRouter>
        <I18nProvider>
          <Chat />
        </I18nProvider>
      </MemoryRouter>,
    );
    const scrollEl = setupScrollEl(container, 1000, 400, 200);
    fireEvent.scroll(scrollEl);

    const jumpBtn = await waitFor(() =>
      screen.getByRole('button', { name: '跳到最新' }),
    );
    fireEvent.click(jumpBtn);

    expect(scrollEl.scrollTop).toBe(1000);
    expect(screen.queryByRole('button', { name: '跳到最新' })).toBeNull();
  });

  it('resets sticky-bottom state when switching sessions', async () => {
    const messages = [baseMsg('1', 'assistant', 'hello')];
    useChatMock.mockReturnValue({
      messages,
      isLoading: true,
      streamingMessageId: '1',
      error: null,
      clearError: vi.fn(),
      sendMessage: vi.fn(),
      interrupt: vi.fn(),
      loadMessages: vi.fn(),
      streamingToolCalls: [],
    });

    const { container, rerender } = render(
      <MemoryRouter>
        <I18nProvider>
          <Chat />
        </I18nProvider>
      </MemoryRouter>,
    );
    const scrollEl = setupScrollEl(container, 1000, 400, 200);
    fireEvent.scroll(scrollEl);
    await waitFor(() => screen.getByRole('button', { name: '跳到最新' }));

    useStore.setState({ currentSessionId: 'session-2' });
    rerender(
      <MemoryRouter>
        <I18nProvider>
          <Chat />
        </I18nProvider>
      </MemoryRouter>,
    );

    expect(screen.queryByRole('button', { name: '跳到最新' })).toBeNull();
  });

  it('sending a new message forces scroll to bottom regardless of prior state', async () => {
    // 初始有 1 条, 用户向上滚(不在底部)
    const messagesV1 = [baseMsg('1', 'assistant', 'hi')];
    useChatMock.mockReturnValue({
      messages: messagesV1,
      isLoading: false,
      streamingMessageId: null,
      error: null,
      clearError: vi.fn(),
      sendMessage: vi.fn(),
      interrupt: vi.fn(),
      loadMessages: vi.fn(),
      streamingToolCalls: [],
    });

    const { container, rerender } = render(
      <MemoryRouter>
        <I18nProvider>
          <Chat />
        </I18nProvider>
      </MemoryRouter>,
    );

    const scrollEl = setupScrollEl(container, /* scrollHeight */ 800, /* clientHeight */ 400, /* scrollTop */ 0);
    fireEvent.scroll(scrollEl); // 不在底部 (800 - 400 - 0 = 400 > 48)

    // 模拟用户发了新消息(消息列表多 1 条)
    const messagesV2 = [...messagesV1, baseMsg('2', 'user', 'new msg')];
    useChatMock.mockReturnValue({
      messages: messagesV2,
      isLoading: false,
      streamingMessageId: null,
      error: null,
      clearError: vi.fn(),
      sendMessage: vi.fn(),
      interrupt: vi.fn(),
      loadMessages: vi.fn(),
      streamingToolCalls: [],
    });
    rerender(
      <MemoryRouter>
        <I18nProvider>
          <Chat />
        </I18nProvider>
      </MemoryRouter>,
    );

    // 发送新消息 → 强制 scroll 到底,即使之前不在底部
    await waitFor(() => {
      expect(scrollEl.scrollTop).toBe(scrollEl.scrollHeight);
    });
  });
});
