/**
 * M4: Chat 页 压缩/分叉 集成测试
 *
 * - /compact slash action → sessionApi.compact(sessionId)；成功/跳过/失败 toast
 * - 消息级 fork → sessionApi.fork(sessionId, messageId) → 切换到新会话
 *   （currentSessionId 变更 = 复用现有 session-switch 路径）+ 成功 toast
 *
 * sessionApi 模块级 mock；其余走真实组件 + zustand store。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Toaster } from 'sonner';
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

const invokeMock = vi.fn();
vi.mock('../../shared/api/desktopInvoke', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
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

import { I18nProvider } from '../../shared/lib/i18n';
import { useStore, type Message as StoreMessage } from '../../shared/lib/store';
import { Chat } from '../Chat';

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

function renderChat() {
  return render(
    <MemoryRouter>
      <I18nProvider defaultLocale="zh">
        <Chat />
        <Toaster />
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe('Chat — M4 compact / fork', () => {
  beforeEach(() => {
    navigateMock.mockReset();
    compactMock.mockReset();
    forkMock.mockReset();
    invokeMock.mockReset();
    // get_messages 返回种子消息（loadMessages effect 不会清空列表），其余命令 → []
    invokeMock.mockImplementation((cmd: string) =>
      Promise.resolve(cmd === 'get_messages' ? seededMessages : []),
    );
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

  function selectCompactFromSlashMenu() {
    const input = screen.getByPlaceholderText(/输入消息/);
    fireEvent.change(input, { target: { value: '/compact' } });
    // 按 role 定位菜单按钮（textarea 里也有 "/compact" 文本）
    fireEvent.mouseDown(screen.getByRole('button', { name: /\/compact/ }));
  }

  it('/compact invokes sessionApi.compact with the current session id and toasts counts', async () => {
    compactMock.mockResolvedValue({
      ok: true,
      compacted: true,
      before: 20,
      after: 8,
      removed: 12,
    });

    renderChat();
    selectCompactFromSlashMenu();

    expect(compactMock).toHaveBeenCalledWith(SESSION_ID);
    expect(await screen.findByText(/上下文已压缩：20 → 8/)).toBeInTheDocument();
  });

  it('/compact shows an info toast when the session is below the floor', async () => {
    compactMock.mockResolvedValue({
      ok: true,
      compacted: false,
      reason: 'below_message_floor',
      before: 4,
      after: 4,
      removed: 0,
    });

    renderChat();
    selectCompactFromSlashMenu();

    expect(await screen.findByText(/对话较短，无需压缩/)).toBeInTheDocument();
  });

  it('/compact shows an error toast on backend failure', async () => {
    compactMock.mockRejectedValue(new Error('upstream 502'));

    renderChat();
    selectCompactFromSlashMenu();

    expect(await screen.findByText(/压缩失败：upstream 502/)).toBeInTheDocument();
  });

  it('message fork invokes sessionApi.fork with (sessionId, messageId) and switches session', async () => {
    forkMock.mockResolvedValue({
      id: 'fork-9',
      title: 'Fork: 测试',
      created_at: 3,
      updated_at: 3,
      last_message_at: null,
      message_count: 1,
      is_pinned: false,
      fork_root: SESSION_ID,
      forked_at_message_id: 'm-1',
    });

    renderChat();

    // 两条种子消息各有一个分叉按钮；点第一条（user 消息 m-1）
    const forkButtons = await screen.findAllByTestId('fork-message');
    expect(forkButtons).toHaveLength(2);
    fireEvent.click(forkButtons[0]);

    expect(forkMock).toHaveBeenCalledWith(SESSION_ID, 'm-1');
    // 复用 session-switch 路径：currentSessionId 切到新会话
    await waitFor(() => expect(useStore.getState().currentSessionId).toBe('fork-9'));
    expect(await screen.findByText(/已分叉为新会话/)).toBeInTheDocument();
  });

  it('fork failure shows an error toast and keeps the current session', async () => {
    forkMock.mockRejectedValue(new Error('session_not_found'));

    renderChat();
    const forkButtons = await screen.findAllByTestId('fork-message');
    fireEvent.click(forkButtons[1]);

    expect(await screen.findByText(/分叉失败：session_not_found/)).toBeInTheDocument();
    expect(useStore.getState().currentSessionId).toBe(SESSION_ID);
  });
});
