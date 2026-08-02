/**
 * M4 MEDIUM-1: 流式进行中（isLoading=true）禁止压缩 / 分叉。
 *
 * useChat 被 mock 成固定 isLoading=true：
 * - 从 slash 菜单选 /compact → sessionApi.compact 不被调用
 *   （ChatInput isLoading 守卫 + handleCompact early-return 双重防线）
 * - 点消息分叉按钮 → sessionApi.fork 不被调用（handleFork early-return）
 *
 * 动机：并发手动压缩会在后端各自通过 should_compact 检查并写出重复续接行；
 * 流式中分叉会复制出不完整的消息序列。
 */
import { fireEvent, render, screen } from '@testing-library/react';
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

const useSettingsMock = vi.fn();
vi.mock('../../features/manage-settings/useSettings', () => ({
  useSettings: () => useSettingsMock(),
}));

vi.mock('../../shared/api/desktopInvoke', () => ({
  invoke: vi.fn().mockResolvedValue([]),
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

const compactMock = vi.fn();
const forkMock = vi.fn();
vi.mock('../../shared/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../shared/api')>();
  return {
    ...actual,
    sessionApi: {
      ...actual.sessionApi,
      compact: (...args: unknown[]) => compactMock(...args),
      fork: (...args: unknown[]) => forkMock(...args),
    },
  };
});

const SESSION_ID = 'sess-1';

const seededMessages: StoreMessage[] = [
  { id: 'm-1', session_id: SESSION_ID, role: 'user', content: '第一条用户消息', created_at: 1 },
  {
    id: 'm-2',
    session_id: SESSION_ID,
    role: 'assistant',
    content: '第一条回复',
    created_at: 2,
  },
];

// 关键：固定 isLoading=true 模拟流式进行中（useChat 内部 state 无法从外部
// 直接驱动，mock 整个 hook 是最干净的注入点）。
vi.mock('../../features/send-message/useChat', () => ({
  useChat: () => ({
    messages: seededMessages,
    isLoading: true,
    error: null,
    clearError: vi.fn(),
    sendMessage: vi.fn(),
    interrupt: vi.fn(),
    loadMessages: vi.fn(),
    currentAgentId: null,
    streamingMessageId: null,
    iteration: 0,
    streamingState: null,
    streamingToolCalls: [],
  }),
}));

import { I18nProvider } from '../../shared/lib/i18n';
import { useStore, type Message as StoreMessage } from '../../shared/lib/store';
import { Chat } from '../Chat';

function renderChat() {
  return render(
    <MemoryRouter>
      <I18nProvider defaultLocale="zh">
        <Chat />
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe('Chat — M4 compact / fork blocked while streaming', () => {
  beforeEach(() => {
    navigateMock.mockReset();
    compactMock.mockReset();
    forkMock.mockReset();
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
    useStore.setState({
      messages: seededMessages,
      currentSessionId: SESSION_ID,
      sessions: [],
      isLoading: false,
    });
  });

  it('/compact during streaming does NOT invoke sessionApi.compact', () => {
    renderChat();

    const input = screen.getByPlaceholderText(/输入消息/);
    fireEvent.change(input, { target: { value: '/compact' } });
    fireEvent.mouseDown(screen.getByRole('button', { name: /\/compact/ }));

    expect(compactMock).not.toHaveBeenCalled();
  });

  it('message fork during streaming does NOT invoke sessionApi.fork', async () => {
    renderChat();

    const forkButtons = await screen.findAllByTestId('fork-message');
    expect(forkButtons.length).toBeGreaterThan(0);
    fireEvent.click(forkButtons[0]);

    expect(forkMock).not.toHaveBeenCalled();
    // 当前会话不切换
    expect(useStore.getState().currentSessionId).toBe(SESSION_ID);
  });
});
