/**
 * U5' (对标增强第五轮批次 A): Chat 页 消息编辑重发集成测试
 *
 * - user 消息显示"编辑并重发"按钮（assistant 没有），点击后原文回填输入框 + 提示条出现
 * - 改写后发送 → fork(sessionId, 目标消息id, undefined, {beforeMessage:true})
 *   → 切换到 fork 会话 → 改写内容发到 fork 会话
 * - fork 失败 → 错误 toast + 退回普通发送（改写内容不丢）
 *
 * sessionApi 模块级 mock；其余走真实组件 + zustand store（复用 compact-fork 模板）。
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

const forkMock = vi.fn();
vi.mock('../../shared/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../shared/api')>();
  return {
    ...actual,
    sessionApi: {
      ...actual.sessionApi,
      fork: (...args: unknown[]) => forkMock(...args),
    },
  };
});

import { I18nProvider } from '../../shared/lib/i18n';
import { useStore, type Message as StoreMessage } from '../../shared/lib/store';
import { Chat } from '../Chat';

// 会话 id 必须是 UUID 形态——chatStream 对 sessionId 做 UUID 校验
const SESSION_ID = 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d';

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

describe('Chat — U5\' 编辑重发', () => {
  beforeEach(() => {
    navigateMock.mockReset();
    forkMock.mockReset();
    invokeMock.mockReset();
    invokeMock.mockImplementation((cmd: string) => {
      if (cmd === 'get_messages') return Promise.resolve(seededMessages);
      if (cmd === 'agent_chat_stream') return Promise.resolve({ streamId: 'st-1' });
      return Promise.resolve([]);
    });
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

  it('user 消息才有编辑按钮；点击回填原文并显示提示条', async () => {
    renderChat();

    const editButtons = await screen.findAllByTestId('edit-resend');
    expect(editButtons).toHaveLength(1); // 只有 user 消息 m-1

    fireEvent.click(editButtons[0]);

    const input = screen.getByPlaceholderText(/输入消息/) as HTMLTextAreaElement;
    expect(input.value).toBe('第一条用户消息');
    expect(screen.getByTestId('edit-resend-banner')).toBeInTheDocument();

    // 取消编辑清空编辑态
    fireEvent.click(screen.getByRole('button', { name: '取消编辑' }));
    expect(screen.queryByTestId('edit-resend-banner')).not.toBeInTheDocument();
  });

  it('改写后发送：开区间 fork → 切换 fork 会话 → 改写内容发到 fork 会话', async () => {
    // fork id 必须是 UUID 形态——chatStream 对 sessionId 做 UUID 校验
    const FORK_ID = '9f1c3b2a-1234-4abc-8def-123456789abc';
    forkMock.mockResolvedValue({
      id: FORK_ID,
      title: 'Fork: 测试',
      created_at: 3,
      updated_at: 3,
      last_message_at: null,
      message_count: 0,
      is_pinned: false,
      fork_root: SESSION_ID,
      forked_at_message_id: 'm-1',
    });

    renderChat();

    fireEvent.click(await screen.findByTestId('edit-resend'));
    const input = screen.getByPlaceholderText(/输入消息/);
    fireEvent.change(input, { target: { value: '改写后的消息' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: false });

    // before_message 开区间语义：截到被编辑消息之前
    await waitFor(() => {
      expect(forkMock).toHaveBeenCalledWith(SESSION_ID, 'm-1', undefined, {
        beforeMessage: true,
      });
    });
    // 复用 session-switch 路径切到 fork 会话
    await waitFor(() => expect(useStore.getState().currentSessionId).toBe(FORK_ID));
    // 改写内容发给 fork 会话（chatStream invoke 载荷）
    await waitFor(() => {
      const streamCall = invokeMock.mock.calls.find(([cmd]) => cmd === 'agent_chat_stream');
      expect(streamCall).toBeDefined();
      expect(streamCall![1]).toMatchObject({ sessionId: FORK_ID, message: '改写后的消息' });
    });
    // 发送后编辑态清空
    expect(screen.queryByTestId('edit-resend-banner')).not.toBeInTheDocument();
    expect(await screen.findByText(/已分叉出新会话/)).toBeInTheDocument();
  });

  it('fork 失败：错误 toast + 退回普通发送（改写内容不丢）', async () => {
    forkMock.mockRejectedValue(new Error('session_not_found'));

    renderChat();

    fireEvent.click(await screen.findByTestId('edit-resend'));
    const input = screen.getByPlaceholderText(/输入消息/);
    fireEvent.change(input, { target: { value: '改写后的消息' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: false });

    expect(await screen.findByText(/分叉失败：session_not_found/)).toBeInTheDocument();
    // 退回普通发送：改写内容发到原会话
    await waitFor(() => {
      const streamCall = invokeMock.mock.calls.find(([cmd]) => cmd === 'agent_chat_stream');
      expect(streamCall).toBeDefined();
      expect(streamCall![1]).toMatchObject({ sessionId: SESSION_ID, message: '改写后的消息' });
    });
    // 编辑态已清空（不会在下次发送时二次分叉）
    expect(screen.queryByTestId('edit-resend-banner')).not.toBeInTheDocument();
  });
});
