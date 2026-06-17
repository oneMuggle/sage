/**
 * useChat hook 测试
 *
 * 策略：mock @tauri-apps/api/core 的 invoke，从而控制 chatApi 的行为；
 * 同时在每个用例前重置 zustand store 与 localStorage，确保测试隔离。
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SETTINGS_STORAGE_KEY, SETTINGS_VERSION } from '../../../entities/setting/types';
import { useStore } from '../../../shared/lib/store';
import { useChat } from '../useChat';

// 必须使用工厂函数，vitest 才能正确 hoist
const invokeMock = vi.fn();
const listenMock = vi.fn();
vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));
vi.mock('../../../shared/api/desktopEvent', () => ({
  listen: (...args: unknown[]) => listenMock(...args),
}));

const VALID_SESSION_ID = '11111111-2222-3333-4444-555555555555';

function seedActiveEndpoint(): void {
  const payload = {
    streaming: true,
    autoMemory: true,
    confirmDelete: true,
    compactMode: false,
    endpoints: [
      {
        id: 'ep-1',
        name: 'Test',
        baseUrl: 'https://api.example.test/v1',
        apiKey: 'sk-test',
        isActive: true,
        discoveredModels: [],
        lastDiscoveredAt: null,
      },
    ],
    modelSelections: {
      chatModelId: 'gpt-test',
      visionModelId: null,
      embeddingModelId: null,
    },
    maxContext: 4096,
    temperature: 0.7,
    proxyMode: 'system',
    proxyUrl: '',
    tlsVersion: '1.2',
    version: SETTINGS_VERSION,
  };
  localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(payload));
}

beforeEach(() => {
  invokeMock.mockReset();
  localStorage.clear();
  useStore.setState({
    sessions: [],
    currentSessionId: VALID_SESSION_ID,
    messages: [],
    isLoading: false,
  });
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

    await act(async () => {
      await result.current.sendMessage('hello');
    });

    expect(result.current.error).toMatch(/未配置 API 地址/);
    expect(invokeMock).not.toHaveBeenCalled();

    // 关键:即使 settings 缺失,user 消息也必须进 store (fix for swallowed input)
    const userMsg = result.current.messages.find((m) => m.role === 'user');
    expect(userMsg).toBeDefined();
    expect(userMsg?.content).toBe('hello');
  });

  it('appends user + assistant message on successful chat', async () => {
    seedActiveEndpoint();
    // PR-6: useChat 改走 chatStream
    invokeMock.mockResolvedValueOnce('stream-1');
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

  // 回归保护: cancel-prev 路径 — sendMessage 必须把 chatStream 返回的
  // cancel 存进 cancelRef, 下次 sendMessage 时 cancel-prev 块会调用它。
  // 真实触发场景: React StrictMode 双调用 / 用户双击 / 路由切换。
  it('stores chatStream cancel into cancelRef for next sendMessage cancellation', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-X' });
    const cancelSpy = vi.fn();
    // listen 返回的 unlisten 函数就是 chatStream 暴露给 cancelRef 的 cancel
    listenMock.mockResolvedValueOnce(cancelSpy);

    const { result } = renderHook(() => useChat());

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
});
