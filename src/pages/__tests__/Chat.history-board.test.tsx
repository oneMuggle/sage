/**
 * C1 (2026-09-09): Chat 历史任务板恢复 测试
 *
 * 会话切换时 Chat 的 hydration effect 拉取该会话最近的编排 run
 * （orchRunClient.listSessionRuns）并写入 chatStreamStore 的任务板槽位：
 *   - 有 run → 恢复 board（runId/plan/statuses/progress）
 *   - 无 run → 不写板（无编排历史是常态）
 *   - 已有直播板（streaming/taskBoard 存在）→ 不覆盖
 *
 * 断言落在 store 槽位而非 RightPanel 挂载 —— 面板默认折叠，store 是
 * hydration 的直接契约。
 */
import { render, waitFor } from '@testing-library/react';
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

const useChatMock = vi.fn();
vi.mock('../../features/send-message/useChat', () => ({
  useChat: () => useChatMock(),
}));

const listSessionRunsMock = vi.fn();
vi.mock('../../shared/api/orchRunClient', () => ({
  orchRunClient: { listSessionRuns: (...args: unknown[]) => listSessionRunsMock(...args) },
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

import { useChatStreamStore } from '../../features/send-message/chatStreamStore';
import { I18nProvider } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';
import { Chat } from '../Chat';


const HISTORY_RUN = {
  run_id: 'orch-h1',
  session_id: 's1',
  status: 'completed',
  created_at: 1700000000000,
  plan: [{ task_id: 't1', agent_id: 'researcher', goal: '调研量化交易' }],
  tasks: [
    {
      task_id: 't1',
      run_id: 'orch-h1',
      agent_id: 'researcher',
      goal: '调研量化交易',
      status: 'done',
      retry_count: 0,
      error: null,
      output_preview: '调研结果摘要',
      started_at: null,
      finished_at: null,
    },
  ],
  original_request: null,
};

function renderChat() {
  return render(
    <MemoryRouter>
      <I18nProvider>
        <Chat />
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe('Chat — 历史任务板恢复（C1）', () => {
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
    useStore.setState({ messages: [], currentSessionId: 's1', sessions: [] });
    useChatStreamStore.setState({ sessions: {} });
    useChatMock.mockReturnValue({
      messages: [],
      isLoading: false,
      error: null,
      clearError: vi.fn(),
      sendMessage: vi.fn(),
      interrupt: vi.fn(),
      loadMessages: vi.fn(),
      streamingToolCalls: [],
    });
  });

  it(' restores the latest run board into the session slot', async () => {
    listSessionRunsMock.mockResolvedValue({ runs: [HISTORY_RUN] });
    renderChat();

    await waitFor(() => {
      const board = useChatStreamStore.getState().sessions['s1']?.taskBoard;
      expect(board?.runId).toBe('orch-h1');
    });
    const board = useChatStreamStore.getState().sessions['s1']!.taskBoard!;
    expect(board.plan[0]).toMatchObject({ task_id: 't1', goal: '调研量化交易' });
    expect(board.statuses['t1']?.status).toBe('done');
    expect(board.progress).toMatchObject({ total: 1, done: 1, running: 0 });
  });

  it('does not write a board when the session has no runs', async () => {
    listSessionRunsMock.mockResolvedValue({ runs: [] });
    renderChat();

    await new Promise((r) => setTimeout(r, 20));
    expect(useChatStreamStore.getState().sessions['s1']?.taskBoard ?? null).toBeNull();
  });

  it('does not clobber an existing live board', async () => {
    useChatStreamStore
      .getState()
      .setTaskBoard('s1', {
        runId: 'orch-live',
        plan: [{ task_id: 't9', agent_id: 'writer', goal: '直播中' }],
        statuses: {},
        progress: { total: 1, done: 0, running: 1, queued: 0, failed: 0, cancelled: 0 },
      });
    listSessionRunsMock.mockResolvedValue({ runs: [HISTORY_RUN] });
    renderChat();

    await new Promise((r) => setTimeout(r, 20));
    const board = useChatStreamStore.getState().sessions['s1']?.taskBoard;
    expect(board?.runId).toBe('orch-live');
  });
});
