/**
 * 对话阅读体验第二轮：useChat 接线 —— C1 DONE 携带的生成统计写入本地 assistant 消息；
 * C2 原位重新生成不追加 user 消息，并把锚点透传给后端。IPC mock 方式与
 * useChat.finishReason.test.ts 相同。
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { usePermissionState } from '../../../entities/permission/permissionState';
import { useQuestionState } from '../../../entities/question/questionState';
import {
  DEFAULT_SETTINGS,
  SETTINGS_STORAGE_KEY,
  SETTINGS_VERSION,
} from '../../../entities/setting/types';
import { useSettingsStore } from '../../../features/manage-settings/settingsStore';
import { useStore, type Message } from '../../../shared/lib/store';
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

const SESSION_ID = '11111111-2222-3333-4444-555555555555';

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
  localStorage.setItem('sage-settings.migrated_to_backend', new Date().toISOString());
}

function seedMessages(messages: Message[]): void {
  useStore.setState({ messages });
}

beforeEach(() => {
  invokeMock.mockReset();
  listenMock.mockReset();
  invokeMock.mockResolvedValueOnce({ data: null });
  localStorage.clear();
  useSettingsStore.setState({ settings: { ...DEFAULT_SETTINGS }, isLoading: true });
  useStore.setState({
    sessions: [],
    currentSessionId: SESSION_ID,
    messages: [],
    isLoading: false,
    contextPressure: null,
  });
  usePermissionState.setState({ currentRequest: null });
  useQuestionState.setState({ currentQuestion: null });
  useChatStreamStore.getState().resetAll();
});

async function sendWithDone(
  done: Record<string, unknown>,
  opts?: Parameters<ReturnType<typeof useChat>['sendMessage']>[4],
  expectedLength = 2,
) {
  seedActiveEndpoint();
  invokeMock.mockResolvedValueOnce({ streamId: 'stream-1' });
  listenMock.mockImplementationOnce(
    async (_name: string, cb: (e: { payload: Record<string, unknown> }) => void) => {
      Promise.resolve().then(() => cb({ payload: { state: 'done', iteration: 1, ...done } }));
      return vi.fn();
    },
  );
  const { result } = renderHook(() => useChat());
  await act(async () => {
    await useSettingsStore.getState().loadSettings();
  });
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  await act(async () => {
    await result.current.sendMessage('ping', SESSION_ID, undefined, undefined, opts);
  });
  await waitFor(() => {
    expect(result.current.messages).toHaveLength(expectedLength);
    expect(result.current.isLoading).toBe(false);
  });
  return result.current.messages;
}

describe('useChat — generation stats (C1)', () => {
  it('records the generation stats carried by DONE', async () => {
    const stats = { output_tokens: 30, first_token_ms: 250, latency_ms: 1500 };
    const messages = await sendWithDone({ content: '答', generation_stats: stats });
    expect(messages[1].generation_stats).toEqual(stats);
  });

  it('leaves generation stats unset when DONE does not carry them', async () => {
    const messages = await sendWithDone({ content: '答' });
    expect(messages[1]).not.toHaveProperty('generation_stats');
  });
});

describe('useChat — in-place regenerate (C2)', () => {
  it('reuses the anchor user message and forwards it to the backend', async () => {
    seedMessages([
      { id: 'u-anchor', session_id: SESSION_ID, role: 'user', content: 'ping', created_at: 1 },
    ]);
    const messages = await sendWithDone({ content: '新的回答' }, { regenerateOf: 'u-anchor' });

    expect(messages.map((m) => m.role)).toEqual(['user', 'assistant']);
    expect(messages[0].id).toBe('u-anchor');
    expect(messages[1].content).toBe('新的回答');
    expect(invokeMock).toHaveBeenCalledWith(
      'agent_chat_stream',
      expect.objectContaining({ regenerateOf: 'u-anchor' }),
    );
  });
});
