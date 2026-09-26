/**
 * 对话阅读体验 B2：DONE 事件携带的 finish_reason 写入本地 assistant 消息，供
 * TruncationNotice 判断是否被输出上限截断。IPC mock 方式与 useChat.test.ts 相同。
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
  // 标记已迁移 → loadSettings() 不会触发 set_settings 自动上传（见 useChat.test.ts）
  localStorage.setItem('sage-settings.migrated_to_backend', new Date().toISOString());
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

async function sendWithDone(done: Record<string, unknown>) {
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
    await result.current.sendMessage('ping');
  });
  await waitFor(() => {
    expect(result.current.messages).toHaveLength(2);
    expect(result.current.isLoading).toBe(false);
  });
  return result.current.messages[1];
}

describe('useChat — finish_reason (B2)', () => {
  it('records a truncation finish_reason on the assistant message', async () => {
    const reply = await sendWithDone({ content: '写到一半', finish_reason: 'length' });
    expect(reply.content).toBe('写到一半');
    expect(reply.finish_reason).toBe('length');
  });

  it('leaves finish_reason unset when DONE does not carry one', async () => {
    const reply = await sendWithDone({ content: '完整回答' });
    expect(reply.content).toBe('完整回答');
    expect(reply).not.toHaveProperty('finish_reason');
  });
});
