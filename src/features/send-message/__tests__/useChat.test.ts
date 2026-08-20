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
 * 仅等到 get_settings 被调用还不够 — settingsClient.getSettings() 的 mockResolvedValue
 * resolve 后, useSettings 的 .then 才会 setSettings, 这个 setter 又触发 React re-render。
 * 三步之间有 microtask gap, 用 act flush 确保 React commit 完成。
 */
async function waitForSettingsLoaded(): Promise<void> {
  await waitFor(() => {
    expect(invokeMock).toHaveBeenCalledWith('get_settings', {});
  });
  // flush useSettings 的 .then(setSettings) + React re-render
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

/** PR-7a: 同 seedActiveEndpoint,但 baseUrl 自由指定(测 provider 推导)。 */
function seedActiveEndpointWithUrl(baseUrl: string): void {
  const payload = {
    streaming: true,
    autoMemory: true,
    confirmDelete: true,
    endpoints: [
      {
        id: 'ep-1',
        name: 'Test',
        baseUrl,
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
  // 标记已迁移 (原因同上)
  localStorage.setItem('sage-settings.migrated_to_backend', new Date().toISOString());
}

beforeEach(() => {
  invokeMock.mockReset();
  listenMock.mockReset();
  // useSettings 异步加载会先调 get_settings；提前 mock 避免它消费测试的
  // mockResolvedValueOnce（后者针对 agent_chat_stream 等具体 cmd）
  invokeMock.mockResolvedValueOnce({ data: null });
  localStorage.clear();
  useStore.setState({
    sessions: [],
    currentSessionId: VALID_SESSION_ID,
    messages: [],
    isLoading: false,
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

describe('useChat', () => {
  it('initial state: empty messages, not loading, no error', () => {
    useStore.setState({ messages: [], currentSessionId: null });
    const { result } = renderHook(() => useChat());

    expect(result.current.messages).toEqual([]);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it('sets error when no active endpoint is configured', async () => {
    // 没有 seed 设置，等同于无 active endpoint
    const { result } = renderHook(() => useChat());

    await waitForSettingsLoaded();

    await act(async () => {
      await result.current.sendMessage('hello');
    });

    expect(result.current.error).toMatch(/未配置 API 地址/);
    // useSettings 异步加载会调 get_settings；断言 agent_chat_stream 没被调
    expect(invokeMock).not.toHaveBeenCalledWith('agent_chat_stream');

    // 关键:即使 settings 缺失,user 消息也必须进 store (fix for swallowed input)
    const userMsg = result.current.messages.find((m) => m.role === 'user');
    expect(userMsg).toBeDefined();
    expect(userMsg?.content).toBe('hello');
  });

  it('appends user + assistant message on successful chat', async () => {
    seedActiveEndpoint();
    // PR-6: useChat 改走 chatStream
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-1' });
    listenMock.mockImplementationOnce(
      async (
        _name: string,
        cb: (e: { payload: { state: string; iteration: number; content?: string } }) => void,
      ) => {
        // 立即同步调 cb 触发 done 事件 (微观队列避免与 state setter 互卡)
        Promise.resolve().then(() =>
          cb({ payload: { state: 'done', iteration: 1, content: 'hi from assistant' } }),
        );
        return vi.fn();
      },
    );

    const { result } = renderHook(() => useChat());

    await waitForSettingsLoaded();

    await act(async () => {
      await result.current.sendMessage('ping');
    });

    // user message + assistant message
    await waitFor(() => {
      expect(result.current.messages).toHaveLength(2);
    });
    expect(result.current.messages[0].role).toBe('user');
    expect(result.current.messages[1].role).toBe('assistant');
    expect(result.current.messages[1].content).toBe('hi from assistant');
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();

    // PR-6: useChat 应该调 agent_chat_stream
    expect(invokeMock).toHaveBeenCalledWith(
      'agent_chat_stream',
      expect.objectContaining({
        sessionId: VALID_SESSION_ID,
        model: 'gpt-test',
      }),
    );
  });

  // PR-7a: useChat 根据 baseUrl 推导 provider 并透传到 IPC,
  // 这样后端 LLMConfig 不再被硬写成 'custom'。
  it('infers provider from Gemini baseUrl and forwards to invoke', async () => {
    seedActiveEndpointWithUrl('https://generativelanguage.googleapis.com/v1beta/openai');
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-gemini' });
    listenMock.mockImplementationOnce(
      async (
        _name: string,
        cb: (e: { payload: { state: string; iteration: number; content?: string } }) => void,
      ) => {
        Promise.resolve().then(() =>
          cb({ payload: { state: 'done', iteration: 0, content: 'gemini says hi' } }),
        );
        return vi.fn();
      },
    );

    const { result } = renderHook(() => useChat());

    await waitForSettingsLoaded();

    await act(async () => {
      await result.current.sendMessage('hello');
    });

    expect(invokeMock).toHaveBeenCalledWith(
      'agent_chat_stream',
      expect.objectContaining({
        provider: 'gemini',
      }),
    );
  });

  it('infers provider from DeepSeek baseUrl and forwards to invoke', async () => {
    seedActiveEndpointWithUrl('https://api.deepseek.com/v1');
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-deepseek' });
    listenMock.mockImplementationOnce(async (_n, cb) => {
      Promise.resolve().then(() => cb({ payload: { state: 'done', iteration: 0, content: 'ok' } }));
      return vi.fn();
    });

    const { result } = renderHook(() => useChat());

    await waitForSettingsLoaded();

    await act(async () => {
      await result.current.sendMessage('hello');
    });

    expect(invokeMock).toHaveBeenCalledWith(
      'agent_chat_stream',
      expect.objectContaining({
        provider: 'deepseek',
      }),
    );
  });

  // 未知 / 自托管 URL → provider 应该是 undefined,后端默认 'custom'
  it('omits provider for unknown baseUrl (falls back to custom)', async () => {
    seedActiveEndpointWithUrl('http://192.168.1.10:11434/v1'); // Ollama
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-ollama' });
    listenMock.mockImplementationOnce(async (_n, cb) => {
      Promise.resolve().then(() => cb({ payload: { state: 'done', iteration: 0, content: 'ok' } }));
      return vi.fn();
    });

    const { result } = renderHook(() => useChat());

    await waitForSettingsLoaded();

    await act(async () => {
      await result.current.sendMessage('hello');
    });

    // useSettings 异步加载先调 get_settings (mock.calls[0])，
    // 第二个 invoke 才是 agent_chat_stream
    const [, args] = invokeMock.mock.calls[1];
    // api.ts 用 `config?.provider ?? null` 转 null,后端收到 null
    // 在 ChatRequest Optional 校验下走默认 "custom"
    expect(args.provider).toBeNull();
  });

  // 回归保护: 真实场景下 NDJSON 事件从主进程 IPC 跨进程过来,
  // 一定晚于 chatStream() 的 await 解析(IPC 是异步 round-trip)。
  // 旧测试用 Promise.resolve().then 调 cb 把事件塞在同一个微任务里,
  // 掩盖了 finally 提前清 streaming state 的 bug。
  it('persists streaming state for events arriving AFTER chatStream() resolves (real IPC timing)', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-real-timing' });

    let capturedCb:
      | ((e: { payload: { state: string; iteration: number; content?: string } }) => void)
      | null = null;
    listenMock.mockImplementationOnce(
      async (
        _name: string,
        cb: (e: { payload: { state: string; iteration: number; content?: string } }) => void,
      ) => {
        // 保存 cb 但不立即调 — 模拟 IPC 事件在 chatStream() 返回后才到
        capturedCb = cb;
        return vi.fn();
      },
    );

    const { result } = renderHook(() => useChat());

    await waitForSettingsLoaded();

    // 启动 sendMessage 但不 await 完(让 finally 跑)
    let sendPromise: Promise<void>;
    await act(async () => {
      sendPromise = result.current.sendMessage('ping') as unknown as Promise<void>;
      // 让 chatStream() 内部的 listen await 完成,sendMessage 同步部分跑完
      await Promise.resolve();
      await Promise.resolve();
      // 此时 finally 应该已跑过(如果 bug 存在,streaming state 被清)
    });

    // 现在模拟 IPC 事件到达 (用 setTimeout 推到下一个 macrotask,
    // 确保在 sendMessage finally 之后)
    await new Promise<void>((r) => setTimeout(r, 0));

    expect(capturedCb).not.toBeNull();
    // 派发 thinking 事件
    act(() => {
      capturedCb!({ payload: { state: 'thinking', iteration: 0 } });
    });
    // 派发 done 事件,带 content
    act(() => {
      capturedCb!({ payload: { state: 'done', iteration: 0, content: 'real-timing answer' } });
    });

    // 关键断言: assistant message 必须有真实 content
    // (旧 bug 下 content 是空 / '🤔 思考中…',永远不更新)
    await waitFor(() => {
      const assistantMsg = result.current.messages.find((m) => m.role === 'assistant');
      expect(assistantMsg?.content).toBe('real-timing answer');
    });

    // 等待 sendMessage 完全结束
    await act(async () => {
      await sendPromise!;
    });
    expect(result.current.isLoading).toBe(false);
  });

  it('preserves optimistic messages across route history reload until stream completion', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-route-switch' });

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

    const { result, unmount } = renderHook(() => useChat());
    await waitForSettingsLoaded();

    let sendPromise: Promise<void>;
    await act(async () => {
      sendPromise = result.current.sendMessage('ping') as unknown as Promise<void>;
      await Promise.resolve();
      await Promise.resolve();
    });

    const optimisticMessages = useStore.getState().messages;
    const userMessage = optimisticMessages.find((message) => message.role === 'user');
    const assistantMessage = optimisticMessages.find((message) => message.role === 'assistant');
    expect(userMessage).toBeDefined();
    expect(assistantMessage).toBeDefined();
    expect(assistantMessage?.content).toBe('🤔 思考中…');
    expect(capturedCb).not.toBeNull();

    // Route switch: the old Chat instance unmounts and the new instance reloads stale history.
    invokeMock.mockImplementation((command: string) => {
      if (command === 'get_settings') return Promise.resolve({ data: null });
      if (command === 'get_messages') {
        return Promise.resolve([
          {
            id: 'old-history-message',
            session_id: VALID_SESSION_ID,
            role: 'user',
            content: 'old history',
            created_at: 1,
          },
        ]);
      }
      return Promise.resolve(undefined);
    });
    unmount();
    renderHook(() => useChat());
    await act(async () => {
      await useStore.getState().loadMessages(VALID_SESSION_ID);
    });

    const afterReload = useStore.getState().messages;
    expect(afterReload).toEqual(expect.arrayContaining([userMessage, assistantMessage]));
    expect(afterReload).toHaveLength(3);

    act(() => {
      capturedCb!({
        payload: { state: 'done', iteration: 1, content: 'route switch answer' },
      });
    });
    await act(async () => {
      await sendPromise!;
    });

    const finalAssistant = useStore
      .getState()
      .messages.find((message) => message.id === assistantMessage?.id);
    expect(finalAssistant?.content).toBe('route switch answer');
    expect(useChatStreamStore.getState().streaming).toBeNull();
  });

  // 回归保护: cancel-prev 路径 — sendMessage 必须把 chatStream 返回的
  // cancel 存进 cancelRef,下次 sendMessage 时 cancel-prev 块会调用它。
  // 真实触发场景: React StrictMode 双调用 / 用户双击 / 路由切换。
  it('stores chatStream cancel into cancelRef for next sendMessage cancellation', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-X' });
    const cancelSpy = vi.fn();
    // listen 返回的 unlisten 函数就是 chatStream 暴露给 cancelRef 的 cancel
    listenMock.mockResolvedValueOnce(cancelSpy);

    const { result } = renderHook(() => useChat());

    await waitForSettingsLoaded();

    // 触发 sendMessage, 让 invoke + listen microtask 都跑完
    // chatStream 内部 listen 的 await resolve 后, sendMessage 同步设置
    // cancelRef.current = cancelSpy, 然后函数自然结束
    await act(async () => {
      result.current.sendMessage('hello');
      await Promise.resolve();
      await Promise.resolve();
    });

    // chatStream 完成后, cancelRef 持有 cancelSpy
    // 通过 interrupt() (用 cancelRef.current) 来间接验证:
    // 如果 cancelRef 是空, interrupt 的 cancel 调用会是 no-op, cancelSpy 不被调
    await act(async () => {
      await result.current.interrupt();
    });

    // interrupt 会调 cancelRef.current() — 我们就是 cancelSpy
    expect(cancelSpy).toHaveBeenCalledTimes(1);
  });

  it('sets error when chat API throws', async () => {
    seedActiveEndpoint();
    // PR-6: listen 抛错 → chatStream reject → handleError
    invokeMock.mockResolvedValueOnce('stream-x');
    listenMock.mockRejectedValueOnce(new Error('event subscribe failed'));

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage('hello');
    });

    await waitFor(() => {
      expect(result.current.error).toBeTruthy();
    });
    expect(result.current.isLoading).toBe(false);
    // 至少包含用户消息
    expect(result.current.messages[0].role).toBe('user');
  }, 15_000);

  it('maps max_iterations_exceeded (stream FAILED with raw code) to actionable Chinese text', async () => {
    // chatApi.ts:198 把 payload.error 包成 new Error(errMsg)，所以 useChat
    // 拿到的就是 raw 错误码字符串。这里必须命中 agent runtime 表 →
    // 中文提示，且不再把裸码暴露给用户。
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-agent-err' });
    let capturedCb:
      | ((e: {
          payload: { state: string; iteration: number; error?: unknown; content?: string };
        }) => void)
      | undefined;
    listenMock.mockImplementationOnce(
      async (
        _name: string,
        cb: (e: {
          payload: { state: string; iteration: number; error?: unknown; content?: string };
        }) => void,
      ) => {
        capturedCb = cb;
        return vi.fn();
      },
    );

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();

    await act(async () => {
      await result.current.sendMessage('big task');
      // 让 listen mock 把 cb 注册上
      await Promise.resolve();
      await Promise.resolve();
    });

    // 模拟后端 run_loop 因 max_iterations 退出 — payload.error 是字符串
    // 错误码，chatApi.ts:196-199 走 typeof errPayload === 'string' 分支。
    await act(async () => {
      capturedCb!({
        payload: {
          state: 'failed',
          iteration: 0,
          error: 'max_iterations_exceeded',
        },
      });
    });

    await waitFor(() => {
      expect(result.current.error).toBeTruthy();
    });
    // 中文提示 + 不再暴露裸码
    expect(result.current.error).toMatch(/迭代/);
    expect(result.current.error).not.toMatch(/max_iterations_exceeded/);
    expect(result.current.isLoading).toBe(false);
  });

  it('passes through unknown stream error message without rewriting it', async () => {
    // 防御：非 agent runtime 码应原样透传（保留网络/HTTP 错误信息），
    // 不能因为加了映射表就吞掉原始 message。
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-unknown-err' });
    let capturedCb:
      | ((e: {
          payload: { state: string; iteration: number; error?: unknown; content?: string };
        }) => void)
      | undefined;
    listenMock.mockImplementationOnce(
      async (
        _name: string,
        cb: (e: {
          payload: { state: string; iteration: number; error?: unknown; content?: string };
        }) => void,
      ) => {
        capturedCb = cb;
        return vi.fn();
      },
    );

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();

    await act(async () => {
      await result.current.sendMessage('hello');
      await Promise.resolve();
      await Promise.resolve();
    });

    await act(async () => {
      capturedCb!({
        payload: {
          state: 'failed',
          iteration: 0,
          error: 'socket hang up',
        },
      });
    });

    await waitFor(() => {
      expect(result.current.error).toBeTruthy();
    });
    expect(result.current.error).toBe('socket hang up');
  });

  it('clearError resets the error state', async () => {
    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage('no endpoint');
    });

    expect(result.current.error).not.toBeNull();

    act(() => {
      result.current.clearError();
    });

    expect(result.current.error).toBeNull();
  });

  it('interrupt swallows errors silently', async () => {
    invokeMock.mockRejectedValueOnce(new Error('interrupt boom'));
    const { result } = renderHook(() => useChat());

    await expect(
      act(async () => {
        await result.current.interrupt();
      }),
    ).resolves.not.toThrow();
  });

  // I5: 流式逐字渲染 — backend producer 把 done.content 拆成 content_delta chunks,
  // useChat 必须累积 chunks 成完整回答 (而不是只显示最后 chunk)。
  // 旧实现是覆盖 (ref = next) — 修成 ref += next 才能逐字增长。
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
        payload: { state: 'acting', iteration: 0, tool_call: { function: { name: 'calculator' } } },
      });
    });
    // 关键断言 2: acting 后应该是 "🔧 调工具 calculator…",之前 thinking 占位已清掉
    const afterActing = result.current.messages.find((m) => m.role === 'assistant');
    expect(afterActing?.content).toBe('🔧 调工具 calculator…');

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

    // 对话框数据到位
    expect(usePermissionState.getState().currentRequest).toEqual(PERM_PAYLOAD);
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

    // 对话框数据到位
    expect(useQuestionState.getState().currentQuestion).toEqual(QUESTION_PAYLOAD);
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
describe('useChat taskBoard', () => {
  it('accumulates task_plan then task_status into board', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-1' });
    listenMock.mockImplementationOnce(
      async (
        _name: string,
        cb: (e: {
          payload: {
            state: string;
            iteration: number;
            content?: string;
            run_id?: string;
            plan?: Array<{ task_id: string; agent_id: string; goal: string }>;
            task_id?: string;
            status?: string;
          };
        }) => void,
      ) => {
        Promise.resolve().then(() => {
          cb({
            payload: {
              state: 'task_plan',
              iteration: 0,
              run_id: 'orch-1',
              plan: [
                { task_id: 't1', agent_id: 'researcher', goal: 'g1' },
                { task_id: 't2', agent_id: 'writer', goal: 'g2' },
              ],
            },
          });
          cb({
            payload: {
              state: 'task_status',
              iteration: 0,
              run_id: 'orch-1',
              task_id: 't1',
              status: 'running',
            },
          });
          cb({
            payload: {
              state: 'task_status',
              iteration: 0,
              run_id: 'orch-1',
              task_id: 't1',
              status: 'done',
            },
          });
          cb({ payload: { state: 'done', iteration: 0, content: 'done' } });
        });
        return vi.fn();
      },
    );

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();
    await act(async () => {
      await result.current.sendMessage('complex task');
    });

    await waitFor(() => {
      expect(result.current.taskBoard).not.toBeNull();
    });
    expect(result.current.taskBoard?.runId).toBe('orch-1');
    expect(result.current.taskBoard?.plan).toHaveLength(2);
    expect(result.current.taskBoard?.statuses.t1?.status).toBe('done');
  });

  it('ignores task_status with mismatched run_id', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-2' });
    listenMock.mockImplementationOnce(
      async (
        _name: string,
        cb: (e: {
          payload: {
            state: string;
            iteration: number;
            content?: string;
            run_id?: string;
            plan?: Array<{ task_id: string; agent_id: string; goal: string }>;
            task_id?: string;
            status?: string;
          };
        }) => void,
      ) => {
        Promise.resolve().then(() => {
          cb({
            payload: {
              state: 'task_plan',
              iteration: 0,
              run_id: 'orch-1',
              plan: [{ task_id: 't1', agent_id: 'researcher', goal: 'g1' }],
            },
          });
          // 旧 run 的 task_status → 应被忽略（statuses 保持空）
          cb({
            payload: {
              state: 'task_status',
              iteration: 0,
              run_id: 'orch-OLD',
              task_id: 't1',
              status: 'done',
            },
          });
          cb({ payload: { state: 'done', iteration: 0, content: 'done' } });
        });
        return vi.fn();
      },
    );

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();
    await act(async () => {
      await result.current.sendMessage('complex');
    });

    await waitFor(() => {
      expect(result.current.taskBoard).not.toBeNull();
    });
    expect(Object.keys(result.current.taskBoard?.statuses ?? {})).toHaveLength(0);
  });

  it('clears taskBoard on new message', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValue({ streamId: 'stream-3' });
    listenMock
      .mockImplementationOnce(
        async (
          _name: string,
          cb: (e: {
            payload: {
              state: string;
              iteration: number;
              content?: string;
              run_id?: string;
              plan?: Array<{ task_id: string; agent_id: string; goal: string }>;
            };
          }) => void,
        ) => {
          Promise.resolve().then(() => {
            cb({
              payload: {
                state: 'task_plan',
                iteration: 0,
                run_id: 'orch-1',
                plan: [{ task_id: 't1', agent_id: 'researcher', goal: 'g1' }],
              },
            });
            cb({ payload: { state: 'done', iteration: 0, content: 'r1' } });
          });
          return vi.fn();
        },
      )
      // 第二条消息不推 task_plan → taskBoard 保持 null
      .mockImplementationOnce(
        async (
          _name: string,
          cb: (e: { payload: { state: string; iteration: number; content?: string } }) => void,
        ) => {
          Promise.resolve().then(() => {
            cb({ payload: { state: 'done', iteration: 0, content: 'r2' } });
          });
          return vi.fn();
        },
      );

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();

    await act(async () => {
      await result.current.sendMessage('m1');
    });
    await waitFor(() => {
      expect(result.current.taskBoard).not.toBeNull();
    });

    // 第二条消息开始时 taskBoard 被清空（streamingToolCalls 清空同处）
    await act(async () => {
      await result.current.sendMessage('m2');
    });
    await waitFor(() => {
      expect(result.current.taskBoard).toBeNull();
    });
  });

  // 进度可视化 P0-2 (2026-08-12): task_progress 初始化 → task_status 重算 5 元组。
  // M3 (code-review): reducer 是"总分一致"核心逻辑，必须有单测兜底。
  it('seeds progress from task_progress then recomputes on task_status', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-3' });
    listenMock.mockImplementationOnce(
      async (
        _name: string,
        cb: (e: {
          payload: {
            state: string;
            iteration: number;
            content?: string;
            run_id?: string;
            plan?: Array<{ task_id: string; agent_id: string; goal: string }>;
            task_id?: string;
            status?: string;
            total?: number;
            done?: number;
            running?: number;
            queued?: number;
            failed?: number;
          };
        }) => void,
      ) => {
        Promise.resolve().then(() => {
          cb({
            payload: {
              state: 'task_plan',
              iteration: 0,
              run_id: 'orch-1',
              plan: [
                { task_id: 't1', agent_id: 'researcher', goal: 'g1' },
                { task_id: 't2', agent_id: 'writer', goal: 'g2' },
              ],
            },
          });
          // 初始化: total=2, 全 queued
          cb({
            payload: {
              state: 'task_progress',
              iteration: 0,
              run_id: 'orch-1',
              total: 2,
              done: 0,
              running: 0,
              queued: 2,
              failed: 0,
            },
          });
          cb({
            payload: {
              state: 'task_status',
              iteration: 0,
              run_id: 'orch-1',
              task_id: 't1',
              status: 'running',
            },
          });
          cb({
            payload: {
              state: 'task_status',
              iteration: 0,
              run_id: 'orch-1',
              task_id: 't1',
              status: 'done',
            },
          });
          cb({ payload: { state: 'done', iteration: 0, content: 'done' } });
        });
        return vi.fn();
      },
    );

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();
    await act(async () => {
      await result.current.sendMessage('complex task');
    });

    await waitFor(() => {
      expect(result.current.taskBoard?.progress).toBeDefined();
    });
    // task_progress 初始化 total=2;随后 t1 running→done,reducer 实时重算。
    // total 保留初始化值 2(plan 数),done=1(t1 终态),queued/running/failed=0。
    expect(result.current.taskBoard?.progress).toEqual({
      total: 2,
      done: 1,
      running: 0,
      queued: 0,
      failed: 0,
    });
  });

  it('falls back to statuses-driven progress when no task_progress arrives', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-4' });
    listenMock.mockImplementationOnce(
      async (
        _name: string,
        cb: (e: {
          payload: {
            state: string;
            iteration: number;
            content?: string;
            run_id?: string;
            plan?: Array<{ task_id: string; agent_id: string; goal: string }>;
            task_id?: string;
            status?: string;
          };
        }) => void,
      ) => {
        Promise.resolve().then(() => {
          cb({
            payload: {
              state: 'task_plan',
              iteration: 0,
              run_id: 'orch-1',
              plan: [
                { task_id: 't1', agent_id: 'researcher', goal: 'g1' },
                { task_id: 't2', agent_id: 'writer', goal: 'g2' },
              ],
            },
          });
          // 老 run: 无 task_progress,只靠 task_status 推。
          // 并发 2 个 running → done,reducer 从 statuses 去重数推 total。
          cb({
            payload: {
              state: 'task_status',
              iteration: 0,
              run_id: 'orch-1',
              task_id: 't1',
              status: 'running',
            },
          });
          cb({
            payload: {
              state: 'task_status',
              iteration: 0,
              run_id: 'orch-1',
              task_id: 't2',
              status: 'running',
            },
          });
          cb({
            payload: {
              state: 'task_status',
              iteration: 0,
              run_id: 'orch-1',
              task_id: 't1',
              status: 'done',
            },
          });
          cb({
            payload: {
              state: 'task_status',
              iteration: 0,
              run_id: 'orch-1',
              task_id: 't2',
              status: 'done',
            },
          });
          cb({ payload: { state: 'done', iteration: 0, content: 'done' } });
        });
        return vi.fn();
      },
    );

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();
    await act(async () => {
      await result.current.sendMessage('complex task');
    });

    await waitFor(() => {
      expect(result.current.taskBoard?.progress).toBeDefined();
    });
    // 无 task_progress → total 从 statuses 去重数(2)推出
    expect(result.current.taskBoard?.progress).toEqual({
      total: 2,
      done: 2,
      running: 0,
      queued: 0,
      failed: 0,
    });
  });
});
