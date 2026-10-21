/**
 * 2026-10-21 step-by-step 流式显示回归测试（win7 移植 main 的三段式 overlay）。
 *
 * 覆盖用户报告的两个缺陷（main 早已修复，本次移植到 release/win7）：
 *
 * - Bug #1「会话切换回流式内容不可见」
 *   复现路径：流式进行中切到别的会话再切回来。此时后端尚未把 assistant 消息
 *   落库，切回时 loadMessages 拉回的会话里只有 user 消息 —— store.messages
 *   中不再有 streamingMessageId 对应的行。旧 derivedMessages 是纯
 *   messages.map()，找不到匹配目标，流式内容就无处渲染。
 *   修复后走"虚拟消息兜底"分支追加一条 assistant 消息承载流式内容。
 *
 * - Bug #2「输出完成后思考内容被替换 → 只剩工具调用」
 *   复现路径：多步 run 中每一步的 reasoning 只能靠 step_done 事件快照进
 *   completedSteps。旧实现没有 step_done handler，步骤级 reasoning 在 store
 *   被服务端消息覆盖后丢失。修复后 step_done handler 把 reasoning 快照进
 *   completedSteps，derivedMessages 在 store 消息之后拼接 completedSteps。
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
import { selectSessionSlots, useChatStreamStore } from '../chatStreamStore';
import { useChat } from '../useChat';

const invokeMock = vi.fn();
const listenMock = vi.fn();
vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));
vi.mock('../../../shared/api/desktopEvent', () => ({
  listen: (...args: unknown[]) => listenMock(...args),
}));

const SESSION_ID = '11111111-2222-3333-4444-555555555555';
const OTHER_SESSION_ID = '99999999-8888-7777-6666-555555555555';

/** 服务端已落库的消息（loadMessages 拉回）。 */
let serverMessages: Message[] = [];
/** 后端 NDJSON 事件回调（listen 捕获，测试手动驱动）。 */
let emit: ((e: { payload: Record<string, unknown> }) => void) | null = null;

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
  localStorage.setItem('sage-settings.migrated_to_backend', new Date().toISOString());
}

beforeEach(() => {
  serverMessages = [];
  emit = null;
  invokeMock.mockReset();
  listenMock.mockReset();
  invokeMock.mockImplementation(async (cmd: string) => {
    if (cmd === 'agent_chat_stream') return { streamId: 'stream-1' };
    if (cmd === 'get_messages') return serverMessages;
    if (cmd === 'list_sessions') return [];
    return undefined;
  });
  listenMock.mockImplementation(
    async (_name: string, cb: (e: { payload: Record<string, unknown> }) => void) => {
      emit = cb;
      return vi.fn();
    },
  );
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

async function startStream(text = 'ping') {
  seedActiveEndpoint();
  const { result } = renderHook(() => useChat());
  await act(async () => {
    await useSettingsStore.getState().loadSettings();
  });
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  await act(async () => {
    await result.current.sendMessage(text);
  });
  expect(emit).not.toBeNull();
  return result;
}

async function emitEvent(payload: Record<string, unknown>): Promise<void> {
  await act(async () => {
    emit?.({ payload });
    await Promise.resolve();
  });
}

function assistantMessages(messages: Message[]): Message[] {
  return messages.filter((m) => m.role === 'assistant');
}

describe('useChat — step-by-step 流式显示 (2026-10-21)', () => {
  it('keeps the streaming reply visible after switching away and back (Bug #1)', async () => {
    const result = await startStream();
    await emitEvent({ state: 'content_delta', iteration: 1, content: '流式正文' });

    // 切到别的会话 —— loadMessages 把 store.messages 换成别的会话的消息
    await act(async () => {
      useStore.setState({ currentSessionId: OTHER_SESSION_ID, messages: [] });
    });
    // 切回来 —— 后端此刻还没落库 assistant 消息，服务端只有 user 消息
    await act(async () => {
      useStore.setState({
        currentSessionId: SESSION_ID,
        messages: [
          { id: 'u-1', session_id: SESSION_ID, role: 'user', content: 'ping', created_at: 1 },
        ],
      });
    });

    const assistants = assistantMessages(result.current.messages);
    expect(assistants).toHaveLength(1);
    expect(assistants[0].content).toContain('流式正文');
  });

  it('snapshots per-step reasoning into completedSteps on step_done (Bug #2)', async () => {
    await startStream();

    await emitEvent({ state: 'reasoning_delta', iteration: 1, reasoning: '先查一下资料' });
    await emitEvent({ state: 'step_done', iteration: 1, step_index: 0 });

    const slots = selectSessionSlots(useChatStreamStore.getState(), SESSION_ID);
    expect(slots.completedSteps).toHaveLength(1);
    expect(slots.completedSteps[0].reasoning_content).toBe('先查一下资料');
    expect(slots.completedSteps[0].step_index).toBe(0);
  });

  it('keeps the per-step reasoning visible after the server messages replace local ones', async () => {
    const result = await startStream();

    await emitEvent({ state: 'reasoning_delta', iteration: 1, reasoning: '先查一下资料' });
    await emitEvent({ state: 'step_done', iteration: 1, step_index: 0 });
    await emitEvent({ state: 'content_delta', iteration: 2, content: '最终答案' });

    // 服务端此刻已有 step0 + 终稿两行 assistant（loadMessages 会拉回它们）
    serverMessages = [
      {
        id: 'u-1',
        session_id: SESSION_ID,
        role: 'user',
        content: 'ping',
        created_at: 1,
      },
      {
        id: 's-0',
        session_id: SESSION_ID,
        role: 'assistant',
        content: '',
        reasoning_content: '先查一下资料',
        step_index: 0,
        created_at: 2,
      },
      {
        id: 's-1',
        session_id: SESSION_ID,
        role: 'assistant',
        content: '最终答案',
        reasoning_content: null,
        step_index: 1,
        created_at: 3,
      },
    ];
    await emitEvent({ state: 'done', iteration: 2, content: '最终答案' });

    await waitFor(() => {
      expect(result.current.messages.some((m) => m.content === '最终答案')).toBe(true);
    });

    // 思考内容仍然可见（来自 completedSteps 快照，不依赖服务端回读）
    const withReasoning = result.current.messages.filter(
      (m) => m.reasoning_content === '先查一下资料',
    );
    expect(withReasoning.length).toBeGreaterThanOrEqual(1);
  });

  it('does not render the same step twice after the server messages land', async () => {
    const result = await startStream();

    await emitEvent({ state: 'reasoning_delta', iteration: 1, reasoning: '先查一下资料' });
    await emitEvent({ state: 'step_done', iteration: 1, step_index: 0 });
    await emitEvent({ state: 'content_delta', iteration: 2, content: '最终答案' });

    serverMessages = [
      {
        id: 'u-1',
        session_id: SESSION_ID,
        role: 'user',
        content: 'ping',
        created_at: 1,
      },
      {
        id: 's-0',
        session_id: SESSION_ID,
        role: 'assistant',
        content: '',
        reasoning_content: '先查一下资料',
        step_index: 0,
        created_at: 2,
      },
      {
        id: 's-1',
        session_id: SESSION_ID,
        role: 'assistant',
        content: '最终答案',
        reasoning_content: null,
        step_index: 1,
        created_at: 3,
      },
    ];
    await emitEvent({ state: 'done', iteration: 2, content: '最终答案' });

    await waitFor(() => {
      expect(result.current.messages.some((m) => m.content === '最终答案')).toBe(true);
    });

    // step 0 只应出现一次（服务端行 + 本地 completedSteps 快照不应叠加）
    const stepZero = assistantMessages(result.current.messages).filter(
      (m) => m.step_index === 0,
    );
    expect(stepZero).toHaveLength(1);
  });
});
