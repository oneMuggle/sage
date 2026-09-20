/**
 * useChat 投递通道测试（插话回显 / steeringAnchorId / 投递分流 P2-a）
 *
 * 策略：mock @tauri-apps/api/core 的 invoke，从而控制 chatApi 的行为；
 * 同时在每个用例前重置 zustand store 与 localStorage，确保测试隔离。
 */
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { usePermissionState } from '../../../entities/permission/permissionState';
import { useQuestionState } from '../../../entities/question/questionState';
import { SETTINGS_STORAGE_KEY, SETTINGS_VERSION } from '../../../entities/setting/types';
import { DEFAULT_SETTINGS } from '../../../entities/setting/types';
import { useSettingsStore } from '../../../features/manage-settings/settingsStore';
import { type Message, useStore } from '../../../shared/lib/store';
import { selectSessionSlots, useChatStreamStore } from '../chatStreamStore';
import { steeringAnchorId, useChat } from '../useChat';

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

// P1 (2026-09-20): 插话（steering）回显的落位与回退语义。
describe('useChat 插话回显', () => {
  it('回显落在本轮流式 assistant 气泡之前（与 DB 顺序一致，避免流末跳位）', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-1' });
    // 不发 done —— 流保持打开，会话维持"忙"
    listenMock.mockImplementationOnce(async () => vi.fn());

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();
    await act(async () => {
      await result.current.sendMessage('原始问题');
    });
    expect(result.current.isLoading).toBe(true);

    invokeMock.mockImplementation(async (cmd: string) =>
      cmd === 'chat_steer' ? { ok: true } : undefined,
    );
    await act(async () => {
      await result.current.sendMessage('第二段太长了');
    });

    expect(invokeMock).toHaveBeenCalledWith(
      'chat_steer',
      expect.objectContaining({ streamId: 'stream-1', content: '第二段太长了' }),
    );
    expect(
      result.current.messages.map((m) => `${m.role}${m.subtype ? `:${m.subtype}` : ''}`),
    ).toEqual(['user', 'user:steering', 'assistant']);
    expect(result.current.messages[1].content).toBe('第二段太长了');
    // 插话成功即生效，不该同时进队列
    expect(
      selectSessionSlots(useChatStreamStore.getState(), VALID_SESSION_ID).pendingQueue,
    ).toEqual([]);
  });

  it('steer 被后端拒绝（409 不在运行窗口）时回退排队，且不产生回显', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-1' });
    listenMock.mockImplementationOnce(async () => vi.fn());

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();
    await act(async () => {
      await result.current.sendMessage('原始问题');
    });

    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'chat_steer') throw new Error('409 not_running');
      return undefined;
    });
    await act(async () => {
      await result.current.sendMessage('排队的那条');
    });

    expect(
      result.current.messages.map((m) => `${m.role}${m.subtype ? `:${m.subtype}` : ''}`),
    ).toEqual(['user', 'assistant']);
    const queued = selectSessionSlots(useChatStreamStore.getState(), VALID_SESSION_ID).pendingQueue;
    expect(queued).toHaveLength(1);
    expect(queued[0].content).toBe('排队的那条');
  });
});

describe('steeringAnchorId', () => {
  const m = (id: string, role: 'user' | 'assistant', subtype?: string): Message => ({
    id,
    session_id: VALID_SESSION_ID,
    role,
    content: id,
    created_at: 1,
    subtype: subtype as Message['subtype'],
  });

  it('锚点 = 本轮最后一条真实用户消息之后的第一条 assistant', () => {
    expect(steeringAnchorId([m('u1', 'user'), m('a1', 'assistant'), m('a2', 'assistant')])).toBe(
      'a1',
    );
  });

  it('多条插话不改变锚点（依次插在同一条 assistant 之前）', () => {
    expect(
      steeringAnchorId([
        m('u1', 'user'),
        m('s1', 'user', 'steering'),
        m('s2', 'user', 'steering'),
        m('a1', 'assistant'),
      ]),
    ).toBe('a1');
  });

  it('本轮还没有 assistant 行时返回 undefined（退回 append）', () => {
    expect(steeringAnchorId([m('u1', 'user'), m('u2', 'user')])).toBeUndefined();
  });
});

// P2-a (2026-09-20): 会话忙时三条投递通道的分流。
describe('useChat 投递通道 (P2-a)', () => {
  /** 起一条不发 done 的流 —— 会话维持"忙"，才能测到忙时分支。 */
  async function startBusyStream(result: { current: ReturnType<typeof useChat> }): Promise<void> {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-1' });
    listenMock.mockImplementationOnce(async () => vi.fn());
    await waitForSettingsLoaded();
    await act(async () => {
      await result.current.sendMessage('原始问题');
    });
    expect(result.current.isLoading).toBe(true);
  }

  const queueOf = () =>
    selectSessionSlots(useChatStreamStore.getState(), VALID_SESSION_ID).pendingQueue;

  it('delivery=queue：不再尝试插话，直接带完整 payload 入队', async () => {
    const { result } = renderHook(() => useChat());
    await startBusyStream(result);
    let steerAttempts = 0;
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'chat_steer') steerAttempts += 1;
      return undefined;
    });

    await act(async () => {
      await result.current.sendMessage(
        '先排着',
        undefined,
        [{ docId: 'd1', docType: 'ppt', filename: 'a.pptx' }],
        undefined,
        { delivery: 'queue', images: ['data:image/png;base64,AAA'] },
      );
    });

    expect(steerAttempts).toBe(0);
    const queued = queueOf();
    expect(queued).toHaveLength(1);
    expect(queued[0].content).toBe('先排着');
    // flush 时要用到的完整快照不能丢（P0 的旧实现只存 content）
    expect(queued[0].opts?.images).toEqual(['data:image/png;base64,AAA']);
    expect(queued[0].officeRefs?.[0].docId).toBe('d1');
  });

  it('delivery=interrupt：先取消当前 run 再立刻发这条，不入队', async () => {
    const { result } = renderHook(() => useChat());
    await startBusyStream(result);
    // 取消会走 finishStream —— 顺带刷新会话与消息，一并 mock 掉
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'chat_steer') throw new Error('interrupt 通道不该插话');
      if (cmd === 'agent_chat_stream') return { streamId: 'stream-2' };
      if (cmd === 'get_messages') return [];
      if (cmd === 'get_settings') return { data: null };
      return undefined;
    });
    listenMock.mockImplementationOnce(async () => vi.fn());

    await act(async () => {
      await result.current.sendMessage('立刻改方向', undefined, undefined, undefined, {
        delivery: 'interrupt',
      });
    });

    // P0-2: 中断必须带 streamId，后端才能命中真实 agent
    expect(invokeMock).toHaveBeenCalledWith('interrupt_agent', { streamId: 'stream-1' });
    expect(
      invokeMock.mock.calls.filter((call: unknown[]) => call[0] === 'agent_chat_stream'),
    ).toHaveLength(2);
    expect(queueOf()).toEqual([]);
    expect(
      result.current.messages.some((msg) => msg.role === 'user' && msg.content === '立刻改方向'),
    ).toBe(true);
  });

  it('不传 delivery 时仍是插话优先（默认通道向后兼容）', async () => {
    const { result } = renderHook(() => useChat());
    await startBusyStream(result);
    invokeMock.mockImplementation(async (cmd: string) =>
      cmd === 'chat_steer' ? { ok: true } : undefined,
    );

    await act(async () => {
      await result.current.sendMessage('默认就是插话');
    });

    expect(invokeMock).toHaveBeenCalledWith(
      'chat_steer',
      expect.objectContaining({ streamId: 'stream-1', content: '默认就是插话' }),
    );
    expect(queueOf()).toEqual([]);
    expect(invokeMock).not.toHaveBeenCalledWith('interrupt_agent', expect.anything());
  });
});
