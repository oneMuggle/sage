// useChat session_updated 增量刷新测试 (2026-11-05)
// 标题事件走 updateSession 增量;其它 subtype 仍全量 loadSessions 兜底。
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
import { useStore, type Session } from '../../../shared/lib/store';
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

let loadSessionsSpy: ReturnType<typeof vi.fn>;

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

function seedSession(title: string): void {
  const session: Session = {
    id: SESSION_ID,
    title,
    created_at: 0,
    updated_at: 0,
    last_message_at: null,
    message_count: 1,
    is_pinned: false,
  };
  useStore.setState({ sessions: [session] });
}

beforeEach(() => {
  invokeMock.mockReset();
  listenMock.mockReset();
  invokeMock.mockResolvedValueOnce({ data: null });
  localStorage.clear();
  useSettingsStore.setState({ settings: { ...DEFAULT_SETTINGS }, isLoading: true });
  loadSessionsSpy = vi.fn().mockResolvedValue(undefined);
  useStore.setState({
    sessions: [],
    currentSessionId: SESSION_ID,
    messages: [],
    isLoading: false,
    contextPressure: null,
    loadSessions: loadSessionsSpy as unknown as () => Promise<void>,
  });
  usePermissionState.setState({ currentRequest: null });
  useQuestionState.setState({ currentQuestion: null });
  useChatStreamStore.getState().resetAll();
});

async function sendWithSessionUpdated(evt: Record<string, unknown>): Promise<void> {
  seedActiveEndpoint();
  invokeMock.mockResolvedValueOnce({ streamId: 'stream-1' });
  listenMock.mockImplementationOnce(
    async (_name: string, cb: (e: { payload: Record<string, unknown> }) => void) => {
      Promise.resolve().then(() => {
        cb({ payload: evt });
        cb({ payload: { state: 'done', iteration: 1, content: 'ok' } });
      });
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
    expect(result.current.isLoading).toBe(false);
  });
}

describe('useChat — session_updated 增量刷新 (2026-11-05)', () => {
  it('title_updated 事件原地更新标题,不做全量会话重载', async () => {
    seedSession('旧标题');
    await sendWithSessionUpdated({
      type: 'session_updated',
      subtype: 'title_updated',
      title: '新标题',
    });
    expect(useStore.getState().sessions[0]?.title).toBe('新标题');
    // 仅 finishStream 兜底一次;事件本身不再触发全量拉取
    expect(loadSessionsSpy).toHaveBeenCalledTimes(1);
  });

  it('其它 subtype 仍走全量 loadSessions 兜底', async () => {
    seedSession('旧标题');
    await sendWithSessionUpdated({
      type: 'session_updated',
      subtype: 'metadata_changed',
    });
    // 事件一次 + finishStream 一次
    expect(loadSessionsSpy).toHaveBeenCalledTimes(2);
  });
});
