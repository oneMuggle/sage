/**
 * useChat — PR C C2: resumeOrchestration 恢复流 + clearTaskBoard 清板。
 *
 * 策略与 useChat.test.ts 一致:mock desktopInvoke/desktopEvent,localStorage
 * 种子 endpoint + settings。resume 路径经 invoke('orchestration_resume_run')
 * → sendMessage(original_request, 'force_multi', {planOverride, runId})。
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { usePermissionState } from '../../../entities/permission/permissionState';
import { useQuestionState } from '../../../entities/question/questionState';
import { SETTINGS_STORAGE_KEY, SETTINGS_VERSION } from '../../../entities/setting/types';
import { useStore } from '../../../shared/lib/store';
import { useChat } from '../useChat';

const invokeMock = vi.fn().mockResolvedValue(undefined);
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

async function waitForSettingsLoaded(): Promise<void> {
  await waitFor(() => {
    expect(invokeMock).toHaveBeenCalledWith('get_settings', {});
  });
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  localStorage.clear();
  invokeMock.mockReset();
  invokeMock.mockResolvedValue(undefined);
  // useSettings 异步加载会先调 get_settings；提前 mock 避免它消费测试的
  // mockResolvedValueOnce（后者针对 orchestration_resume_run 等具体 cmd）
  invokeMock.mockResolvedValueOnce({ data: null });
  listenMock.mockReset();
  // sendMessage 内 `sid = sessionId ?? currentSessionId` —— 缺 session 直接 return
  useStore.setState({
    sessions: [],
    currentSessionId: VALID_SESSION_ID,
    messages: [],
    isLoading: false,
  });
  // M1: 隔离 permission/question store,避免用例间状态串扰
  usePermissionState.setState({ currentRequest: null });
  useQuestionState.setState({ currentQuestion: null });
});

describe('useChat.resumeOrchestration (PR C C2)', () => {
  it('resumeRun → sendMessage(original_request, force_multi, planOverride+new_run_id)', async () => {
    seedActiveEndpoint();
    const plan = [{ task_id: 't1', agent_id: 'researcher', goal: 'G' }];
    // 调用序: get_settings(beforeEach 兜底) → orchestration_resume_run → agent_chat_stream
    invokeMock
      .mockResolvedValueOnce({
        ok: true,
        new_run_id: 'orch-new',
        session_id: 's',
        original_request: '恢复原计划',
        plan,
      })
      .mockResolvedValueOnce({ streamId: 'stream-resume' });
    listenMock.mockImplementationOnce(async (_n, cb) => {
      Promise.resolve().then(() => cb({ payload: { state: 'done', iteration: 0, content: 'ok' } }));
      return vi.fn();
    });

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();

    await act(async () => {
      await result.current.resumeOrchestration('orch-old');
    });

    expect(invokeMock).toHaveBeenCalledWith('orchestration_resume_run', {
      run_id: 'orch-old',
    });
    // get_settings + orchestration_resume_run 之后第三个 invoke 才是 agent_chat_stream
    const [, args] = invokeMock.mock.calls[2];
    expect(args.message).toBe('恢复原计划');
    expect(args.orchestrationMode).toBe('force_multi');
    expect(args.plan_override).toEqual(plan);
    expect(args.run_id).toBe('orch-new');
  });

  it('original_request 缺失 → 占位文案发送 + toast 提示', async () => {
    seedActiveEndpoint();
    const plan = [{ task_id: 't1', agent_id: 'researcher', goal: 'G' }];
    const toastInfoSpy = vi.spyOn(toast, 'info').mockImplementation(() => '');
    invokeMock
      .mockResolvedValueOnce({
        ok: true,
        new_run_id: 'orch-new',
        session_id: 's',
        original_request: null,
        plan,
      })
      .mockResolvedValueOnce({ streamId: 'stream-resume' });
    listenMock.mockImplementationOnce(async (_n, cb) => {
      Promise.resolve().then(() => cb({ payload: { state: 'done', iteration: 0, content: 'ok' } }));
      return vi.fn();
    });

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();

    await act(async () => {
      await result.current.resumeOrchestration('orch-old');
    });

    const [, args] = invokeMock.mock.calls[2];
    expect(args.message).toBe('（旧记录无原始请求，已从计划恢复）');
    expect(args.orchestrationMode).toBe('force_multi');
    expect(toastInfoSpy).toHaveBeenCalledWith('该记录缺少原始请求，已从计划恢复执行');
    toastInfoSpy.mockRestore();
  });
});

describe('useChat.clearTaskBoard (PR C C2)', () => {
  it('清空 task_plan 事件建立的任务板', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-board' });
    listenMock.mockImplementationOnce(async (_n, cb) => {
      Promise.resolve().then(() =>
        cb({
          payload: {
            state: 'task_plan',
            run_id: 'r1',
            plan: [{ task_id: 't1', agent_id: 'researcher', goal: 'G' }],
            iteration: 0,
          },
        }),
      );
      return vi.fn();
    });

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();

    await act(async () => {
      await result.current.sendMessage('plan it');
    });
    // task_plan 事件在微任务中异步触发 → 用 waitFor 而非同步断言
    await waitFor(() => {
      expect(result.current.taskBoard?.runId).toBe('r1');
    });

    await act(async () => {
      result.current.clearTaskBoard();
    });
    expect(result.current.taskBoard).toBeNull();
  });
});
