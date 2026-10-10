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
import { selectSessionSlots, useChatStreamStore } from '../chatStreamStore';
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
      cancelled: 0,
    });
  });

  // P0-6 (2026-08-20): task_review 事件 → 复核结论写入任务板,
  // 由 TaskTreeSection 渲染横幅。不进消息气泡（agentStateMapping 对
  // task_review 返回 null 的既有行为保留）。
  it('stores task_review event on the task board', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-1' });
    listenMock.mockImplementationOnce(
      async (_name: string, cb: (e: { payload: Record<string, unknown> }) => void) => {
        Promise.resolve().then(() => {
          cb({
            payload: {
              state: 'task_plan',
              iteration: 0,
              run_id: 'orch-1',
              plan: [{ task_id: 't1', agent_id: 'researcher', goal: 'g1' }],
            },
          });
          cb({
            payload: {
              state: 'task_review',
              iteration: 0,
              run_id: 'orch-1',
              task_id: 't1',
              reviewer_id: 'reviewer',
              verdict: 'fail',
              assertion_count: 3,
              summary: '结论缺少数据支撑',
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
      const board = selectSessionSlots(useChatStreamStore.getState(), VALID_SESSION_ID).taskBoard;
      expect(board?.review?.verdict).toBe('fail');
      expect(board?.review?.summary).toBe('结论缺少数据支撑');
    });
  });

  // r72 回归 + R38 修正: skill_activated 明细必须写在 user 消息上（技能由用户输入触发），
  // 后端 legacy_routes.py:3350 将 activated_skills 写入 user message。
  it('routes skill_activated payload to the user message', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-skills' });
    listenMock.mockImplementationOnce(
      async (_name: string, cb: (e: { payload: Record<string, unknown> }) => void) => {
        Promise.resolve().then(() => {
          cb({
            payload: {
              state: 'skill_activated',
              iteration: 0,
              skills: [{ name: 'report-writing', triggers_matched: ['/report'] }],
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
      await result.current.sendMessage('写一份报告');
    });

    await waitFor(() => {
      // R38: 技能激活明细写入 user 消息（后端 legacy_routes.py:3350 同口径）
      const user = useStore.getState().messages.find((m) => m.role === 'user');
      expect(user?.activated_skills).toEqual([
        { name: 'report-writing', triggers_matched: ['/report'] },
      ]);
    });
    // assistant 消息不携带技能明细
    const assistant = useStore.getState().messages.find((m) => m.role === 'assistant');
    expect(assistant?.activated_skills).toBeUndefined();
  });
  // r77 回归: 重接(reattach)重放时 memory_used 也要写入 memory_refs,
  // 与主路径同口径 —— 否则页面刷新后完成的消息丢失记忆明细。
  it('routes memory_used payload to memory_refs on replay', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-mem' });
    const memPayload = [{ id: 'mem-1', memory_type: 'long', preview: '命中记忆' }];
    listenMock.mockImplementationOnce(
      async (_name: string, cb: (e: { payload: Record<string, unknown> }) => void) => {
        Promise.resolve().then(() => {
          cb({
            payload: {
              state: 'memory_used',
              iteration: 0,
              memories: memPayload,
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
      await result.current.sendMessage('带记忆的提问');
    });

    await waitFor(() => {
      const assistant = useStore.getState().messages.find((m) => m.role === 'assistant');
      expect(assistant?.memory_refs).toEqual(memPayload);
      expect(assistant?.memory_applied).toBe(1);
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
      cancelled: 0,
    });
  });
});

// ─── live-events P2 (2026-09-07): agent 工具单次委派 → 合成轻量任务板 ───
