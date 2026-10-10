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

describe('useChat subagent_event synthesized board (agent tool)', () => {
  it('synthesizes a board from agent-* events without a task_plan', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-agent-live' });
    listenMock.mockImplementationOnce(
      async (_name: string, cb: (e: { payload: Record<string, unknown> }) => void) => {
        Promise.resolve().then(() => {
          cb({
            payload: {
              state: 'subagent_event',
              iteration: 0,
              run_id: 'agent-abc123def456',
              task_id: 'a1',
              agent_id: 'subagent',
              goal: '调研依赖',
              phase: 'tool_call',
              live_step: '🔧 read_file docs/a.md',
              ts: 1700000000000,
            },
          });
          cb({
            payload: {
              state: 'task_status',
              iteration: 0,
              run_id: 'agent-abc123def456',
              task_id: 'a1',
              status: 'done',
              agent_id: 'subagent',
              goal: '调研依赖',
              error: null,
              output_preview: '调研结论',
              retry_count: 0,
            },
          });
        });
        return vi.fn();
      },
    );

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();
    await act(async () => {
      await result.current.sendMessage('go');
    });

    await waitFor(() => {
      const board = result.current.taskBoard;
      expect(board?.runId).toBe('agent-abc123def456');
      expect(board?.statuses['a1']?.status).toBe('done');
    });
    const board = result.current.taskBoard;
    expect(board?.plan).toHaveLength(1);
    expect(board?.plan[0]).toMatchObject({ task_id: 'a1', agent_id: 'subagent' });
    expect(board?.live?.['a1']?.liveStep).toBe('🔧 read_file docs/a.md');
  });

  it('does not clobber an existing orchestration board with agent-* events', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-agent-guard' });
    listenMock.mockImplementationOnce(
      async (_name: string, cb: (e: { payload: Record<string, unknown> }) => void) => {
        Promise.resolve().then(() => {
          // 先建立编排板（正常多 agent 流程）
          cb({
            payload: {
              state: 'task_plan',
              iteration: 0,
              run_id: 'orch-real',
              plan: [{ task_id: 't1', agent_id: 'researcher', goal: '编排目标' }],
            },
          });
          // 随后到达异 run 的 agent-* 事件 —— 不应替换编排板
          cb({
            payload: {
              state: 'subagent_event',
              iteration: 0,
              run_id: 'agent-zzz',
              task_id: 'a1',
              agent_id: 'subagent',
              goal: '串扰尝试',
              phase: 'tool_call',
              live_step: '🔧 x',
            },
          });
        });
        return vi.fn();
      },
    );

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();
    await act(async () => {
      await result.current.sendMessage('go');
    });

    await waitFor(() => {
      expect(result.current.taskBoard?.runId).toBe('orch-real');
    });
    const board = result.current.taskBoard;
    expect(board?.plan).toHaveLength(1);
    expect(board?.plan[0]?.goal).toBe('编排目标');
    expect(board?.live?.['a1']).toBeUndefined();
  });

  // ── R38 MEDIUM-2: SSE 载荷运行时校验 ──────────────────────────────
  // 畸形载荷必须被丢弃（不更新 UI），合法载荷正常消费。
  describe('R38 透明度事件载荷校验', () => {
    async function setupCapture() {
      seedActiveEndpoint();
      invokeMock.mockResolvedValueOnce({ streamId: 'stream-r38' });
      let capturedCb: ((e: unknown) => void) | null = null;
      listenMock.mockImplementationOnce(async (_name: string, cb: (e: unknown) => void) => {
        capturedCb = cb;
        return vi.fn();
      });
      const { result } = renderHook(() => useChat());
      await waitForSettingsLoaded();
      await act(async () => {
        // 不驱动 done：本组用例只验证事件载荷校验，流保持挂起即可
        (result.current.sendMessage('ping') as unknown as Promise<void>).catch(() => {});
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(capturedCb).not.toBeNull();
      return { result, capturedCb: capturedCb! };
    }

    it('compact_triggered 字段类型不符（string 而非 number）→ 丢弃, 不插入系统消息', async () => {
      const { result, capturedCb } = await setupCapture();
      const before = result.current.messages.length;

      act(() => {
        capturedCb({
          payload: {
            state: 'compact_triggered',
            iteration: 0,
            compact: { before: '20', after: 8, removed: 12 },
          },
        });
      });

      expect(result.current.messages.length).toBe(before);
      expect(result.current.messages.some((m) => m.compact_info)).toBe(false);
    });

    it('compact_triggered 合法 → 插入带 compact_info 的系统消息', async () => {
      const { result, capturedCb } = await setupCapture();

      act(() => {
        capturedCb({
          payload: {
            state: 'compact_triggered',
            iteration: 0,
            compact: { before: 20, after: 8, removed: 12 },
          },
        });
      });

      const compactMsg = result.current.messages.find((m) => m.compact_info);
      expect(compactMsg).toBeDefined();
      expect(compactMsg?.compact_info).toEqual({ before: 20, after: 8, removed: 12 });
    });

    it('TM2: context_pressure 合法 → 写入 store 供水位徽章渲染', async () => {
      const { capturedCb } = await setupCapture();

      act(() => {
        capturedCb({
          payload: {
            state: 'context_pressure',
            iteration: 0,
            context_pressure: {
              total_tokens: 1200,
              budget_tokens: 3000,
              pressure: 0.4,
              by_role: { system: 200, user: 500, assistant: 500 },
              estimator: 'estimate_messages_tokens',
            },
          },
        });
      });

      const cp = useStore.getState().contextPressure;
      expect(cp).not.toBeNull();
      expect(cp?.pressure).toBe(0.4);
      expect(cp?.total_tokens).toBe(1200);
    });

    it('TM2: context_pressure 载荷非法（pressure 非 number）→ 丢弃', async () => {
      const { capturedCb } = await setupCapture();

      act(() => {
        capturedCb({
          payload: {
            state: 'context_pressure',
            iteration: 0,
            context_pressure: {
              total_tokens: 'many',
              budget_tokens: 3000,
              pressure: 'high',
              by_role: {},
              estimator: 'estimate_messages_tokens',
            },
          },
        });
      });

      expect(useStore.getState().contextPressure).toBeNull();
    });

    it('skill_activated 条目 name 非字符串 → 丢弃, 不写 activated_skills', async () => {
      const { result, capturedCb } = await setupCapture();

      act(() => {
        capturedCb({
          payload: {
            state: 'skill_activated',
            iteration: 0,
            skills: [{ name: 123, triggers_matched: [] }],
          },
        });
      });

      const userMsg = result.current.messages.find((m) => m.role === 'user');
      expect(userMsg?.activated_skills).toBeUndefined();
    });

    it('skill_activated 合法 → 命中触发词写入用户消息', async () => {
      const { result, capturedCb } = await setupCapture();

      act(() => {
        capturedCb({
          payload: {
            state: 'skill_activated',
            iteration: 0,
            skills: [{ name: 'deploy', triggers_matched: ['部署'] }],
          },
        });
      });

      const userMsg = result.current.messages.find((m) => m.role === 'user');
      expect(userMsg?.activated_skills).toEqual([{ name: 'deploy', triggers_matched: ['部署'] }]);
    });

    it('memory_used 条目缺 id → 丢弃, 不写 memory_refs', async () => {
      const { result, capturedCb } = await setupCapture();

      act(() => {
        capturedCb({
          payload: {
            state: 'memory_used',
            iteration: 0,
            memories: [{ preview: '没有 id 的脏数据' }],
          },
        });
      });

      const asstMsg = result.current.messages.find((m) => m.role === 'assistant');
      expect(asstMsg?.memory_refs).toBeUndefined();
      expect(asstMsg?.memory_applied).toBeUndefined();
    });
  });

  describe('R81 sources_used 载荷校验', () => {
    async function setupCapture() {
      seedActiveEndpoint();
      invokeMock.mockResolvedValueOnce({ streamId: 'stream-r58' });
      let capturedCb: ((e: unknown) => void) | null = null;
      listenMock.mockImplementationOnce(async (_name: string, cb: (e: unknown) => void) => {
        capturedCb = cb;
        return vi.fn();
      });
      const { result } = renderHook(() => useChat());
      await waitForSettingsLoaded();
      await act(async () => {
        (result.current.sendMessage('ping') as unknown as Promise<void>).catch(() => {});
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(capturedCb).not.toBeNull();
      return { result, capturedCb: capturedCb! };
    }

    it('合法 sources → 写入 assistant 消息', async () => {
      const { result, capturedCb } = await setupCapture();

      act(() => {
        capturedCb({
          payload: {
            state: 'sources_used',
            iteration: 0,
            sources: [
              { kind: 'web', title: 'Sage', url: 'https://sage.example.com', snippet: '官网' },
              { kind: 'wiki', path: 'wiki/arch.md', title: '架构', snippet: '分层', score: 0.9 },
              { kind: 'tool', server: 'github', tool: 'search', preview: 'issues' },
            ],
          },
        });
      });

      const asstMsg = result.current.messages.find((m) => m.role === 'assistant');
      expect(asstMsg?.sources).toHaveLength(3);
      expect(asstMsg?.sources?.[0]).toMatchObject({ kind: 'web', url: 'https://sage.example.com' });
    });

    it('kind 非法 → 整批丢弃, 不写 sources', async () => {
      const { result, capturedCb } = await setupCapture();

      act(() => {
        capturedCb({
          payload: {
            state: 'sources_used',
            iteration: 0,
            sources: [{ kind: 'hacker-news', title: '伪造来源' }],
          },
        });
      });

      const asstMsg = result.current.messages.find((m) => m.role === 'assistant');
      expect(asstMsg?.sources).toBeUndefined();
    });

    it('attachment_rag_used 多事件按 media_id 合并, 不再整体覆盖', async () => {
      const { result, capturedCb } = await setupCapture();

      act(() => {
        capturedCb({
          payload: {
            state: 'attachment_rag_used',
            iteration: 0,
            citations: [{ media_id: 'doc1', filename: 'a.pdf', mode: 'rag', chunks: [] }],
          },
        });
      });
      act(() => {
        capturedCb({
          payload: {
            state: 'attachment_rag_used',
            iteration: 0,
            citations: [{ media_id: 'doc2', filename: 'b.pdf', mode: 'rag', chunks: [] }],
          },
        });
      });

      const asstMsg = result.current.messages.find((m) => m.role === 'assistant');
      expect(asstMsg?.rag_citations).toHaveLength(2);
      expect(asstMsg?.rag_citations?.map((c) => c.media_id)).toEqual(['doc1', 'doc2']);
    });
  });
});
