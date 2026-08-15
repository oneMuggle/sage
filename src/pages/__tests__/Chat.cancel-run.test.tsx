/**
 * Chat 页 — 编排统一取消 handleCancelRun 测试 (Wave 3 C4+H1, 2026-08-15)
 *
 * 覆盖 Chat.tsx 中：
 *   - handleCancelRun(runId)：未派发/已派发/运行中一律调 orchRunClient.cancelRun
 *     （后端置 cancelled + dispatcher.cancel() 阻止自动派发，避免空转烧 token）
 *     → 成功或失败都 clearTaskBoard()（M1 .catch 兜底）。
 *   - H1：未派发取消不再"仅前端清理"——必须调后端 cancelRun。
 *   - H2：已派发运行中 → TaskTreeSection 出现取消按钮并走同一路径。
 *
 * 渲染链路真实：Chat → RightPanel → ProgressSection → PlanCard(未派发)/
 * TaskTreeSection(已派发)。useChat / orchRunClient 都被 mock，
 * ChatInput 也 mock 掉避免 AtFileMenu 依赖。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => vi.fn(),
  };
});

const useSettingsMock = vi.fn();
vi.mock('../../features/manage-settings/useSettings', () => ({
  useSettings: () => useSettingsMock(),
}));

const useChatMock = vi.fn();
const clearTaskBoardMock = vi.fn();
vi.mock('../../features/send-message/useChat', () => ({
  useChat: () => useChatMock(),
}));

const cancelRunMock = vi.fn();
vi.mock('../../shared/api/orchRunClient', () => ({
  orchRunClient: {
    listRuns: vi.fn().mockResolvedValue([]),
    cancelRun: (...args: unknown[]) => cancelRunMock(...args),
  },
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
    resumeOrchestration: vi.fn(),
    clearTaskBoard: clearTaskBoardMock,
    ...overrides,
  };
}

function board(dispatchedAt: number | null) {
  return {
    runId: 'run-1',
    plan: [{ task_id: 't1', agent_id: 'researcher', goal: 'G' }],
    statuses: {},
    dispatchedAt,
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

describe('Chat — handleCancelRun 统一取消 (Wave 3 C4+H1)', () => {
  beforeEach(() => {
    useSettingsMock.mockReturnValue({
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
      updateSettings: vi.fn(),
      resetSettings: vi.fn(),
    });
    useStore.setState({ messages: [], currentSessionId: 'session-ws', sessions: [] });
    clearTaskBoardMock.mockClear();
    cancelRunMock.mockReset();
    cancelRunMock.mockResolvedValue({ ok: true, run_id: 'run-1', status: 'cancelled' });
  });

  it('未派发：点 plan-cancel → cancelRun(runId) + clearTaskBoard (H1)', async () => {
    useChatMock.mockReturnValue(baseChat({ taskBoard: board(null) }));
    renderChat();
    expect(screen.getByTestId('plan-cancel')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('plan-cancel'));
    await waitFor(() => expect(cancelRunMock).toHaveBeenCalledWith('run-1'));
    expect(clearTaskBoardMock).toHaveBeenCalled();
  });

  it('已派发运行中：task-tree 取消按钮 → cancelRun(runId) + clearTaskBoard (H2)', async () => {
    useChatMock.mockReturnValue(baseChat({ taskBoard: board(Date.now()) }));
    renderChat();
    expect(screen.getByTestId('task-tree-cancel')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('task-tree-cancel'));
    await waitFor(() => expect(cancelRunMock).toHaveBeenCalledWith('run-1'));
    expect(clearTaskBoardMock).toHaveBeenCalled();
  });

  it('cancelRun 失败(409)→ clearTaskBoard 仍执行 (M1 .catch 兜底)', async () => {
    cancelRunMock.mockRejectedValue(new Error('run already terminal'));
    useChatMock.mockReturnValue(baseChat({ taskBoard: board(null) }));
    renderChat();
    fireEvent.click(screen.getByTestId('plan-cancel'));
    await waitFor(() => expect(clearTaskBoardMock).toHaveBeenCalled());
  });
});
