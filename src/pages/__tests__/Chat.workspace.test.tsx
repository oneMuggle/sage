/**
 * Chat 页 — WorkspaceContext wire-in 测试 (Office M1-M2 chat-read closure +
 * Task 5, 2026-07-26 SessionWorkspaceProvider migration).
 *
 * 覆盖 Chat.tsx 中：
 *   - Chat imports useCurrentWorkspace() from shared/lib/workspaceContext
 *   - Chat reads the workspace path from the WorkspaceContext provider
 *   - Chat forwards `workspacePath` into the <ChatInput> rendered below it
 *
 * 关闭整个 Critical #1：Chat.tsx 把 workspacePath 注入 ChatInput → AtFileMenu
 * 链。三种状态各覆盖：
 *   1. provider 提供具体路径 → ChatInput 收到该路径
 *   2. provider 提供 null binding → ChatInput 收到 undefined
 *   3. 没有 provider → ChatInput 收到 undefined (useContext fallback)
 *
 * 不发起任何真实 IPC/localStorage;useSettings / useChat / fileSearchClient
 * 都被 mock；workspaceApi 也被 mock 以避免走真实后端。
 */
import { render, screen, waitFor } from '@testing-library/react';
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

vi.mock('../../features/send-message/useChat', () => ({
  useChat: () => ({
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
  }),
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

// Capture what ChatInput actually receives from Chat, so we can assert
// the workspacePath prop traveled all the way through. The real ChatInput
// is rendered — but its children (AtFileMenu) won't show because query is null.
const chatInputPropsSpy = vi.fn();
vi.mock('../../widgets/chat/ChatInput', () => ({
  ChatInput: (props: Record<string, unknown>) => {
    chatInputPropsSpy(props);
    return (
      <div data-testid="chat-input-mock">
        <span data-testid="chat-input-workspace">{String(props.workspacePath)}</span>
      </div>
    );
  },
  MessageList: () => null,
  ActiveAgentIndicator: () => null,
}));

// Task 5: workspaceApi is now the source of truth — stub it so the
// provider's get() resolves with the requested binding shape.
const mockGet = vi.fn();
vi.mock('../../shared/api/workspaceApi', () => ({
  workspaceApi: {
    bind: vi.fn().mockResolvedValue({ binding: null }),
    get: (...args: unknown[]) => mockGet(...args),
    revoke: vi.fn().mockResolvedValue({ revoked: true, generation: 1 }),
  },
}));

import { SessionWorkspaceProvider } from '../../app/providers/SessionWorkspaceProvider';
import { I18nProvider } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';
import { Chat } from '../Chat';

function renderChat(workspaceValue: string | undefined) {
  chatInputPropsSpy.mockClear();
  mockGet.mockReset();
  mockGet.mockResolvedValue({
    binding: workspaceValue
      ? {
          sessionId: 'session-ws',
          workspacePath: workspaceValue,
          generation: 1,
          activatedAt: 0,
          revokedAt: null,
        }
      : null,
  });
  return render(
    <MemoryRouter>
      <I18nProvider>
        <SessionWorkspaceProvider>
          <Chat />
        </SessionWorkspaceProvider>
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe('Chat — workspacePath wire-in (Office M1-M2 chat-read closure + Task 5)', () => {
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
  });

  it('forwards WorkspaceContext value to ChatInput as workspacePath prop', async () => {
    renderChat('/w/my-project');
    expect(screen.getByTestId('chat-input-mock')).toBeInTheDocument();
    await waitFor(() => {
      const calls = chatInputPropsSpy.mock.calls;
      const props = calls[calls.length - 1][0] as Record<string, unknown>;
      expect(props.workspacePath).toBe('/w/my-project');
    });
    expect(screen.getByTestId('chat-input-workspace').textContent).toBe('/w/my-project');
  });

  it('passes undefined to ChatInput when binding is null', async () => {
    renderChat(undefined);
    await waitFor(() => {
      const calls = chatInputPropsSpy.mock.calls;
      const props = calls[calls.length - 1][0] as Record<string, unknown>;
      expect(props.workspacePath).toBeUndefined();
    });
  });

  it('falls back to undefined when no SessionWorkspaceProvider is mounted', async () => {
    chatInputPropsSpy.mockClear();
    mockGet.mockReset();
    render(
      <MemoryRouter>
        <I18nProvider>
          <Chat />
        </I18nProvider>
      </MemoryRouter>,
    );
    await waitFor(() => {
      const calls = chatInputPropsSpy.mock.calls;
      const props = calls[calls.length - 1][0] as Record<string, unknown>;
      expect(props.workspacePath).toBeUndefined();
    });
  });
});
