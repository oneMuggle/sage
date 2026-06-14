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
