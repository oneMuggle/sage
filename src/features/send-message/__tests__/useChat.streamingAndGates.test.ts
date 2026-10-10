/**
 * useChat hook 测试
 *
 * 策略：mock @tauri-apps/api/core 的 invoke，从而控制 chatApi 的行为；
 * 同时在每个用例前重置 zustand store 与 localStorage，确保测试隔离。
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { usePermissionState } from '../../../entities/permission/permissionState';
import { useQuestionState } from '../../../entities/question/questionState';
import { SETTINGS_STORAGE_KEY, SETTINGS_VERSION } from '../../../entities/setting/types';
import { DEFAULT_SETTINGS } from '../../../entities/setting/types';
import { useSettingsStore } from '../../../features/manage-settings/settingsStore';
import { useStore } from '../../../shared/lib/store';
import { useChatStreamStore } from '../chatStreamStore';
import { useChat } from '../useChat';

// 必须使用工厂函数，vitest 才能正确 hoist
// 默认 mockResolvedValue(undefined) 让未 mock 的 IPC 调用（如 useSettings
// 异步触发的 get_settings）也能 resolve 到 undefined，避免 Promise 挂死
// 阻塞 useChat 后续流程。具体 cmd 的 mock 通过 mockResolvedValueOnce 覆盖。
const invokeMock = vi.fn().mockResolvedValue(undefined);
const listenMock = vi.fn();
vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));
vi.mock('../../../shared/api/desktopEvent', () => ({
  listen: (...args: unknown[]) => listenMock(...args),
}));


const VALID_SESSION_ID = '11111111-2222-3333-4444-555555555555';

/**
 * useSettings 现在 async；renderHook 之后 settings 还在 loading。
 * 在测试里调 sendMessage 前等 get_settings invoke 完成 + React state setter flush，
 * 否则 useSettings 还是 DEFAULT_SETTINGS，useChat 会误判无 endpoint。
 *
 * 2026-08-26: useSettings 改为订阅全局 zustand store 后, loadSettings 不再
 * 在 mount 时自动触发. 显式调 store.loadSettings() 启动加载.
 */
async function waitForSettingsLoaded(): Promise<void> {
  await act(async () => {
    await useSettingsStore.getState().loadSettings();
  });
  // flush React re-render
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function seedActiveEndpoint(): void {
  const payload = {
    streaming: true,
    autoMemory: true,
    confirmDelete: true,
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
    version: SETTINGS_VERSION,
  };
  localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(payload));
  // 标记已迁移 → loadSettings() 不会触发 set_settings 自动上传
  // (否则 mockResolvedValueOnce 会被 set_settings 消费掉,
  //  agent_chat_stream 拿到默认 undefined,chatStream 解构 streamId 报错)
  localStorage.setItem('sage-settings.migrated_to_backend', new Date().toISOString());
}

beforeEach(() => {
  invokeMock.mockReset();
  listenMock.mockReset();
  // useSettings 异步加载会先调 get_settings；提前 mock 避免它消费测试的
  // mockResolvedValueOnce（后者针对 agent_chat_stream 等具体 cmd）
  invokeMock.mockResolvedValueOnce({ data: null });
  localStorage.clear();
  // 2026-08-26: 重置 settings store,避免用例间串扰
  useSettingsStore.setState({ settings: { ...DEFAULT_SETTINGS }, isLoading: true });
  useStore.setState({
    sessions: [],
    currentSessionId: VALID_SESSION_ID,
    messages: [],
    isLoading: false,
    contextPressure: null,
  });
  // M1: 隔离 permission store,避免用例间对话框状态串扰
  usePermissionState.setState({ currentRequest: null });
  // M2 part B: 同理隔离 question store
  useQuestionState.setState({ currentQuestion: null });
  useChatStreamStore.getState().resetAll();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useChat streaming deltas & gates', () => {
  it('accumulates content_delta chunks into full assistant content', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-chunks' });

    let capturedCb:
      | ((e: { payload: { state: string; iteration: number; content?: string } }) => void)
      | null = null;
    listenMock.mockImplementationOnce(
      async (
        _name: string,
        cb: (e: { payload: { state: string; iteration: number; content?: string } }) => void,
      ) => {
        capturedCb = cb;
        return vi.fn();
      },
    );

    const { result } = renderHook(() => useChat());

    await waitForSettingsLoaded();

    let sendPromise: Promise<void>;
    await act(async () => {
      sendPromise = result.current.sendMessage('你好') as unknown as Promise<void>;
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(capturedCb).not.toBeNull();

    // 模拟 producer 拆 3 个 chunk + thinking 占位 + done 收尾
    act(() => {
      capturedCb!({ payload: { state: 'thinking', iteration: 0 } });
    });
    act(() => {
      capturedCb!({ payload: { state: 'content_delta', iteration: 1, content: '你好,' } });
    });
    act(() => {
      capturedCb!({ payload: { state: 'content_delta', iteration: 1, content: '我是 ' } });
    });
    act(() => {
      capturedCb!({ payload: { state: 'content_delta', iteration: 1, content: 'Sage' } });
    });
    act(() => {
      capturedCb!({ payload: { state: 'done', iteration: 1, content: '你好,我是 Sage' } });
    });

    // 关键断言: assistant message 的 content 必须是完整累积,不是最后 chunk "Sage"
    await waitFor(() => {
      const assistantMsg = result.current.messages.find((m) => m.role === 'assistant');
      expect(assistantMsg?.content).toBe('你好,我是 Sage');
    });

    await act(async () => {
      await sendPromise!;
    });
    expect(result.current.isLoading).toBe(false);
  });

  // I5-2 回归保护: thinking/acting/observing 的 uiText 必须 REPLACE 而不是 APPEND,
  // 否则会出现 "🤔 思考中…🤔 思考中…" 这种重复前缀。
  // 旧实现 append 导致每次 state event 都拼到 ref 上,最终 done.content 还要被
  // ref 里的占位符污染 (用 lastDoneContent 修复)。本次把 uiText 改成 replace,
  // 让 state event 清掉之前的占位符,真正累积只来自 content_delta。
  it('replaces thinking/acting/observing uiText (no double-prefix bug)', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-states' });

    let capturedCb:
      | ((e: {
          payload: {
            state: string;
            iteration: number;
            content?: string;
            tool_call?: { function: { name: string } };
          };
        }) => void)
      | null = null;
    listenMock.mockImplementationOnce(
      async (
        _name: string,
        cb: (e: {
          payload: {
            state: string;
            iteration: number;
            content?: string;
            tool_call?: { function: { name: string } };
          };
        }) => void,
      ) => {
        capturedCb = cb;
        return vi.fn();
      },
    );

    const { result } = renderHook(() => useChat());

    await waitForSettingsLoaded();

    let sendPromise: Promise<void>;
    await act(async () => {
      sendPromise = result.current.sendMessage('hi') as unknown as Promise<void>;
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(capturedCb).not.toBeNull();

    // 模拟 producer: thinking → acting → observing → content_delta* → done
    act(() => {
      capturedCb!({ payload: { state: 'thinking', iteration: 0 } });
    });
    // 关键断言 1: thinking 后 content 应该是单个 "🤔 思考中…",不是重复
    const afterThinking = result.current.messages.find((m) => m.role === 'assistant');
    expect(afterThinking?.content).toBe('🤔 思考中…');

    act(() => {
      capturedCb!({
        payload: { state: 'acting', iteration: 0, tool_call: { function: { name: 'read_file' } } },
      });
    });
    // 关键断言 2: acting 后应该是 "🔧 调工具 read_file…",之前 thinking 占位已清掉
    const afterActing = result.current.messages.find((m) => m.role === 'assistant');
    expect(afterActing?.content).toBe('🔧 调工具 read_file…');

    act(() => {
      capturedCb!({ payload: { state: 'observing', iteration: 0 } });
    });
    const afterObserving = result.current.messages.find((m) => m.role === 'assistant');
    expect(afterObserving?.content).toBe('👀 观察结果…');

    // content_delta chunks 走 append,累积到当前 content (当前是 observing 占位)
    act(() => {
      capturedCb!({ payload: { state: 'content_delta', iteration: 1, content: '答' } });
    });
    act(() => {
      capturedCb!({ payload: { state: 'content_delta', iteration: 1, content: '案是' } });
    });
    act(() => {
      capturedCb!({ payload: { state: 'content_delta', iteration: 1, content: ' 2' } });
    });
    // chunks 期间 uiText 占位保留作为视觉上下文(让用户看到 "刚才在观察,现在答案出来")
    const afterChunks = result.current.messages.find((m) => m.role === 'assistant');
    expect(afterChunks?.content).toBe('👀 观察结果…答案是 2');

    // done 事件触发 finishStream, lastDoneContent 覆盖 store content → 清掉占位
    act(() => {
      capturedCb!({ payload: { state: 'done', iteration: 1, content: '答案是 2' } });
    });

    await act(async () => {
      await sendPromise!;
    });
    // 最终 store content = lastDoneContent (clean)
    const final = result.current.messages.find((m) => m.role === 'assistant');
    expect(final?.content).toBe('答案是 2');
    expect(result.current.isLoading).toBe(false);
  });
});

// ============================================================================
// M1 工具安全加固: permission_request 流事件 → permission store 接线
// ============================================================================
describe('useChat M1 permission_request wiring', () => {
  type PermEvt = {
    payload: {
      state: string;
      iteration: number;
      agent_id?: string | null;
      content?: string;
      permission_request?: {
        request_id: string;
        tool_name: string;
        args_summary: string;
        risk: 'safe' | 'suspicious' | 'destructive';
        message: string;
        created_at: number;
      };
    };
  };

  const PERM_PAYLOAD = {
    request_id: 'perm-req-1',
    tool_name: 'terminal',
    args_summary: '{"command": "ls"}',
    risk: 'suspicious' as const,
    message: 'execute 能力工具 terminal 需要用户逐次确认',
    created_at: 1753718400.123,
  };

  it('permission_request event populates the permission store for the dialog', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-perm' });

    let capturedCb: ((e: PermEvt) => void) | null = null;
    listenMock.mockImplementationOnce(async (_name: string, cb: (e: PermEvt) => void) => {
      capturedCb = cb;
      return vi.fn();
    });

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();

    let sendPromise: Promise<void>;
    await act(async () => {
      sendPromise = result.current.sendMessage('帮我跑 ls') as unknown as Promise<void>;
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(capturedCb).not.toBeNull();
    expect(usePermissionState.getState().currentRequest).toBeNull();

    // acting → permission_request（后端 gate 开始阻塞等待应答）
    act(() => {
      capturedCb!({ payload: { state: 'acting', iteration: 0 } });
    });
    act(() => {
      capturedCb!({
        payload: {
          state: 'permission_request',
          iteration: 0,
          agent_id: null,
          permission_request: PERM_PAYLOAD,
        },
      });
    });

    // 对话框数据到位（S4: currentRequest 附带来源会话 id）
    expect(usePermissionState.getState().currentRequest).toEqual({
      ...PERM_PAYLOAD,
      session_id: VALID_SESSION_ID,
    });
    // 且没有污染消息气泡（permission_request 不产生占位文本,保留 acting 占位）
    const mid = result.current.messages.find((m) => m.role === 'assistant');
    expect(mid?.content).toBe('🔧 行动中…');

    // 用户批准后后端继续: observing → done
    act(() => {
      capturedCb!({ payload: { state: 'observing', iteration: 0 } });
    });
    act(() => {
      capturedCb!({ payload: { state: 'done', iteration: 1, content: 'ls 输出' } });
    });
    await act(async () => {
      await sendPromise!;
    });

    // 流结束 → finishStream 清掉遗留对话框
    expect(usePermissionState.getState().currentRequest).toBeNull();
    expect(result.current.isLoading).toBe(false);
  });

  it('stream error path also resolves a pending permission request', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-perm-fail' });

    let capturedCb: ((e: PermEvt) => void) | null = null;
    listenMock.mockImplementationOnce(async (_name: string, cb: (e: PermEvt) => void) => {
      capturedCb = cb;
      return vi.fn();
    });

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();

    let sendPromise: Promise<void>;
    await act(async () => {
      sendPromise = result.current.sendMessage('rm -rf /') as unknown as Promise<void>;
      await Promise.resolve();
      await Promise.resolve();
    });

    act(() => {
      capturedCb!({
        payload: {
          state: 'permission_request',
          iteration: 0,
          permission_request: { ...PERM_PAYLOAD, request_id: 'perm-fail' },
        },
      });
    });
    expect(usePermissionState.getState().currentRequest?.request_id).toBe('perm-fail');

    // failed 事件 → onError + finishStream → resolve()
    act(() => {
      capturedCb!({ payload: { state: 'failed', iteration: 0, content: 'boom' } });
    });
    await act(async () => {
      await sendPromise!;
    });

    expect(usePermissionState.getState().currentRequest).toBeNull();
  });

  it('permission_request event without payload is ignored (defensive)', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-perm-empty' });

    let capturedCb: ((e: PermEvt) => void) | null = null;
    listenMock.mockImplementationOnce(async (_name: string, cb: (e: PermEvt) => void) => {
      capturedCb = cb;
      return vi.fn();
    });

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();

    let sendPromise: Promise<void>;
    await act(async () => {
      sendPromise = result.current.sendMessage('hi') as unknown as Promise<void>;
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(capturedCb).not.toBeNull();

    // 缺少 permission_request 载荷 → 防御性跳过,不写 store
    act(() => {
      capturedCb!({ payload: { state: 'permission_request', iteration: 0 } });
    });
    expect(usePermissionState.getState().currentRequest).toBeNull();

    act(() => {
      capturedCb!({ payload: { state: 'done', iteration: 1, content: 'ok' } });
    });
    await act(async () => {
      await sendPromise!;
    });

    expect(usePermissionState.getState().currentRequest).toBeNull();
  });
});

// ============================================================================
// M2 part B: ask_user_question 流事件 → question store 接线
// ============================================================================
describe('useChat M2 ask_user_question wiring', () => {
  type QuestionEvt = {
    payload: {
      state: string;
      iteration: number;
      agent_id?: string | null;
      content?: string;
      user_question?: {
        request_id: string;
        question: string;
        header?: string | null;
        options: Array<{ label: string; description?: string | null }>;
        multi_select: boolean;
        created_at: number;
      };
    };
  };

  const QUESTION_PAYLOAD = {
    request_id: 'q-req-1',
    question: '选择输出格式?',
    header: '输出格式',
    options: [
      { label: 'Markdown', description: '纯文本报告' },
      { label: 'PDF', description: '排版文档' },
    ],
    multi_select: false,
    created_at: 1753718400.123,
  };

  it('ask_user_question event populates the question store for the dialog', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-q' });

    let capturedCb: ((e: QuestionEvt) => void) | null = null;
    listenMock.mockImplementationOnce(async (_name: string, cb: (e: QuestionEvt) => void) => {
      capturedCb = cb;
      return vi.fn();
    });

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();

    let sendPromise: Promise<void>;
    await act(async () => {
      sendPromise = result.current.sendMessage('给我个报告') as unknown as Promise<void>;
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(capturedCb).not.toBeNull();
    expect(useQuestionState.getState().currentQuestion).toBeNull();

    // acting → ask_user_question（后端 gate 开始阻塞等待应答）
    act(() => {
      capturedCb!({ payload: { state: 'acting', iteration: 0 } });
    });
    act(() => {
      capturedCb!({
        payload: {
          state: 'ask_user_question',
          iteration: 0,
          agent_id: null,
          user_question: QUESTION_PAYLOAD,
        },
      });
    });

    // 对话框数据到位（S4: currentQuestion 附带来源会话 id）
    expect(useQuestionState.getState().currentQuestion).toEqual({
      ...QUESTION_PAYLOAD,
      session_id: VALID_SESSION_ID,
    });
    // 且没有污染消息气泡（ask_user_question 不产生占位文本,保留 acting 占位）
    const mid = result.current.messages.find((m) => m.role === 'assistant');
    expect(mid?.content).toBe('🔧 行动中…');

    // 用户应答后后端继续: observing → done
    act(() => {
      capturedCb!({ payload: { state: 'observing', iteration: 0 } });
    });
    act(() => {
      capturedCb!({ payload: { state: 'done', iteration: 1, content: '按 PDF 输出' } });
    });
    await act(async () => {
      await sendPromise!;
    });

    // 流结束 → finishStream 清掉遗留对话框
    expect(useQuestionState.getState().currentQuestion).toBeNull();
    expect(result.current.isLoading).toBe(false);
  });

  it('stream error path also resolves a pending question', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-q-fail' });

    let capturedCb: ((e: QuestionEvt) => void) | null = null;
    listenMock.mockImplementationOnce(async (_name: string, cb: (e: QuestionEvt) => void) => {
      capturedCb = cb;
      return vi.fn();
    });

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();

    let sendPromise: Promise<void>;
    await act(async () => {
      sendPromise = result.current.sendMessage('x') as unknown as Promise<void>;
      await Promise.resolve();
      await Promise.resolve();
    });

    act(() => {
      capturedCb!({
        payload: {
          state: 'ask_user_question',
          iteration: 0,
          user_question: { ...QUESTION_PAYLOAD, request_id: 'q-fail' },
        },
      });
    });
    expect(useQuestionState.getState().currentQuestion?.request_id).toBe('q-fail');

    // failed 事件 → onError + finishStream → resolve()
    act(() => {
      capturedCb!({ payload: { state: 'failed', iteration: 0, content: 'boom' } });
    });
    await act(async () => {
      await sendPromise!;
    });

    expect(useQuestionState.getState().currentQuestion).toBeNull();
  });

  it('ask_user_question event without payload is ignored (defensive)', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-q-empty' });

    let capturedCb: ((e: QuestionEvt) => void) | null = null;
    listenMock.mockImplementationOnce(async (_name: string, cb: (e: QuestionEvt) => void) => {
      capturedCb = cb;
      return vi.fn();
    });

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();

    let sendPromise: Promise<void>;
    await act(async () => {
      sendPromise = result.current.sendMessage('hi') as unknown as Promise<void>;
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(capturedCb).not.toBeNull();

    // 缺少 user_question 载荷 → 防御性跳过,不写 store
    act(() => {
      capturedCb!({ payload: { state: 'ask_user_question', iteration: 0 } });
    });
    expect(useQuestionState.getState().currentQuestion).toBeNull();

    act(() => {
      capturedCb!({ payload: { state: 'done', iteration: 1, content: 'ok' } });
    });
    await act(async () => {
      await sendPromise!;
    });

    expect(useQuestionState.getState().currentQuestion).toBeNull();
  });
});

// ============================================================================
// Multi-Agent Orchestration: task_plan / task_status 流事件 → taskBoard 聚合
// ============================================================================
