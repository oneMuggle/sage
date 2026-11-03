/**
 * useChat 思考过程参数透传测试。
 *
 * 2026-11-03: per-endpoint 思考过程参数落地。
 *
 * 回归背景：用户反馈 win7 安装包非流式输出看不到思考过程。根因是端点配置里
 * 从来没有思考参数，前端恒发 null，上游模型从未被请求进入思考模式。
 * 本测试锁住「端点配置 → ChatConfig → invoke body」这一段透传。
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { usePermissionState } from '../../../entities/permission/permissionState';
import { useQuestionState } from '../../../entities/question/questionState';
import {
  DEFAULT_SETTINGS,
  SETTINGS_STORAGE_KEY,
  SETTINGS_VERSION,
} from '../../../entities/setting/types';
import { useSettingsStore } from '../../../features/manage-settings/settingsStore';
import { useStore } from '../../../shared/lib/store';
import { useChatStreamStore } from '../chatStreamStore';
import { useChat } from '../useChat';

const invokeMock = vi.fn().mockResolvedValue(undefined);
const listenMock = vi.fn();
vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));
vi.mock('../../../shared/api/desktopEvent', () => ({
  listen: (...args: unknown[]) => listenMock(...args),
}));

import { createFakeStream, done } from './fixtures/fakeStream';

const VALID_SESSION_ID = '11111111-2222-3333-4444-555555555555';

/**
 * 播种一个带思考参数的 active endpoint。
 * `reasoningEffort` / `thinkingBudget` 为 null 时表示"未配置"。
 */
function seedEndpointWithReasoning(
  reasoningEffort: 'low' | 'medium' | 'high' | null,
  thinkingBudget: number | null,
): void {
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
        reasoningEffort,
        thinkingBudget,
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
  localStorage.setItem('sage-settings.migrated_to_backend', new Date().toISOString());
}

async function waitForSettingsLoaded(): Promise<void> {
  await act(async () => {
    await useSettingsStore.getState().loadSettings();
  });
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  invokeMock.mockReset();
  listenMock.mockReset();
  invokeMock.mockResolvedValueOnce({ data: null });
  localStorage.clear();
  useSettingsStore.setState({ settings: { ...DEFAULT_SETTINGS }, isLoading: true });
  useStore.setState({
    sessions: [],
    currentSessionId: VALID_SESSION_ID,
    messages: [],
    isLoading: false,
    contextPressure: null,
  });
  usePermissionState.setState({ currentRequest: null });
  useQuestionState.setState({ currentQuestion: null });
  useChatStreamStore.getState().resetAll();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useChat 思考过程参数透传', () => {
  it('把端点的 reasoningEffort / thinkingBudget 透传到 agent_chat_stream', async () => {
    seedEndpointWithReasoning('high', 4096);
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-reasoning' });
    listenMock.mockImplementationOnce(createFakeStream([done('ok', 1)]).listen);

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();

    await act(async () => {
      await result.current.sendMessage('hello');
    });

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith(
        'agent_chat_stream',
        expect.objectContaining({
          reasoningEffort: 'high',
          thinkingBudget: 4096,
        }),
      );
    });
  });

  it('端点未配置思考参数时保持 null（上游不进入思考模式，行为不变）', async () => {
    seedEndpointWithReasoning(null, null);
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-none' });
    listenMock.mockImplementationOnce(createFakeStream([done('ok', 1)]).listen);

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();

    await act(async () => {
      await result.current.sendMessage('hello');
    });

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith(
        'agent_chat_stream',
        expect.objectContaining({
          reasoningEffort: null,
          thinkingBudget: null,
        }),
      );
    });
  });

  it('thinkingBudget = 0 原样透传（显式关闭思考，不被当成"未设置"）', async () => {
    seedEndpointWithReasoning(null, 0);
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-zero' });
    listenMock.mockImplementationOnce(createFakeStream([done('ok', 1)]).listen);

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();

    await act(async () => {
      await result.current.sendMessage('hello');
    });

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith(
        'agent_chat_stream',
        expect.objectContaining({
          reasoningEffort: null,
          thinkingBudget: 0,
        }),
      );
    });
  });
});
