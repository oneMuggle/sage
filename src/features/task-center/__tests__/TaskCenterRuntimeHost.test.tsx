import { render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/api/shellApi', () => ({ listShells: vi.fn() }));

import { listShells } from '../../../shared/api/shellApi';
import { TaskCenterRuntimeHost } from '../TaskCenterRuntimeHost';
import { useTaskCenterStore } from '../taskCenterStore';
import { resetUnifiedTaskStore, useUnifiedTaskStore } from '../unifiedTaskStore';

/**
 * 轮询节拍。刻意在此独立写死（不从实现模块 import 常量）——
 * 若共用常量，实现改了节拍用例也跟着改，节拍就再也锁不住。
 */
const GOAL_POLL_MS = 10_000;
const SLOW_SOURCE_POLL_MS = 30_000;

/**
 * 把三源刷新动作 mock 掉：
 * 1. 避免真实网络调用（listGoals / todoClient / scheduledClient）
 * 2. 让"是否被调用"成为可精确断言的观测点
 */
function mockUnifiedRefreshers() {
  const state = useUnifiedTaskStore.getState();
  return {
    refreshGoals: vi.spyOn(state, 'refreshGoals').mockResolvedValue(undefined),
    refreshTodos: vi.spyOn(state, 'refreshTodos').mockResolvedValue(undefined),
    refreshScheduled: vi.spyOn(state, 'refreshScheduled').mockResolvedValue(undefined),
  };
}

describe('TaskCenterRuntimeHost', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.resetAllMocks();
    useTaskCenterStore.setState({ tasks: {} });
    resetUnifiedTaskStore();
    // 阻止 mount 时的 refresh() 覆盖测试数据
    vi.spyOn(useUnifiedTaskStore.getState(), 'refresh').mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('挂载即拉一次 shell 列表', async () => {
    vi.mocked(listShells).mockResolvedValue([]);
    render(<TaskCenterRuntimeHost />);
    await vi.waitFor(() => expect(listShells).toHaveBeenCalledTimes(1));
  });

  it('按 3s 轮询 shell', async () => {
    vi.mocked(listShells).mockResolvedValue([]);
    render(<TaskCenterRuntimeHost />);
    await vi.waitFor(() => expect(listShells).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(3_000);
    expect(listShells).toHaveBeenCalledTimes(2);
  });

  it('shell 列表同步进 taskCenterStore', async () => {
    vi.mocked(listShells).mockResolvedValue([
      { shell_id: 'sh-1', command: 'npm test', status: 'running', exit_code: null, age_seconds: 3 },
    ] as never);
    render(<TaskCenterRuntimeHost />);
    await vi.waitFor(() =>
      expect(useTaskCenterStore.getState().tasks['shell:sh-1']).toMatchObject({
        kind: 'shell',
        shellId: 'sh-1',
      }),
    );
  });

  it('渲染 null', () => {
    vi.mocked(listShells).mockResolvedValue([]);
    const { container } = render(<TaskCenterRuntimeHost />);
    expect(container.firstChild).toBeNull();
  });

  it('挂载时拉一次三源 refresh', () => {
    vi.mocked(listShells).mockResolvedValue([]);
    const refresh = useUnifiedTaskStore.getState().refresh;
    render(<TaskCenterRuntimeHost />);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('goal 轮询仅在存在非终态目标时继续', async () => {
    vi.mocked(listShells).mockResolvedValue([]);
    const { refreshGoals } = mockUnifiedRefreshers();
    useUnifiedTaskStore.setState({ goals: [{ id: 'g1', name: 'g', status: 'running' } as never] });

    render(<TaskCenterRuntimeHost />);
    await vi.advanceTimersByTimeAsync(GOAL_POLL_MS);
    expect(refreshGoals).toHaveBeenCalled();

    useUnifiedTaskStore.setState({
      goals: [{ id: 'g1', name: 'g', status: 'completed' } as never],
    });
    refreshGoals.mockClear();
    await vi.advanceTimersByTimeAsync(GOAL_POLL_MS);
    expect(refreshGoals).not.toHaveBeenCalled();
  });

  it('goal 轮询节拍为 10s', async () => {
    vi.mocked(listShells).mockResolvedValue([]);
    const { refreshGoals } = mockUnifiedRefreshers();
    useUnifiedTaskStore.setState({ goals: [{ id: 'g1', name: 'g', status: 'running' } as never] });

    render(<TaskCenterRuntimeHost />);
    await vi.advanceTimersByTimeAsync(GOAL_POLL_MS - 1);
    expect(refreshGoals).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(refreshGoals).toHaveBeenCalledTimes(1);
  });

  it('goal 门控：pending/paused 保持轮询，completed/failed/cancelled 停止轮询', async () => {
    vi.mocked(listShells).mockResolvedValue([]);
    const { refreshGoals } = mockUnifiedRefreshers();

    render(<TaskCenterRuntimeHost />);

    for (const status of ['pending', 'running', 'paused'] as const) {
      useUnifiedTaskStore.setState({ goals: [{ id: 'g1', name: 'g', status } as never] });
      refreshGoals.mockClear();
      await vi.advanceTimersByTimeAsync(GOAL_POLL_MS);
      expect(refreshGoals, `status=${status} 应保持轮询`).toHaveBeenCalledTimes(1);
    }

    for (const status of ['completed', 'failed', 'cancelled'] as const) {
      useUnifiedTaskStore.setState({ goals: [{ id: 'g1', name: 'g', status } as never] });
      refreshGoals.mockClear();
      await vi.advanceTimersByTimeAsync(GOAL_POLL_MS);
      expect(refreshGoals, `status=${status} 应停止轮询`).not.toHaveBeenCalled();
    }
  });

  it('todo 轮询：存在 in_progress todo 时按 30s 调用 refreshTodos', async () => {
    vi.mocked(listShells).mockResolvedValue([]);
    const { refreshTodos } = mockUnifiedRefreshers();
    useUnifiedTaskStore.setState({
      todos: [{ id: 1, title: 't', status: 'in_progress' } as never],
    });

    render(<TaskCenterRuntimeHost />);
    await vi.advanceTimersByTimeAsync(SLOW_SOURCE_POLL_MS - 1);
    expect(refreshTodos).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(refreshTodos).toHaveBeenCalledTimes(1);
  });

  it('todo 轮询：无 in_progress todo 时不调用 refreshTodos', async () => {
    vi.mocked(listShells).mockResolvedValue([]);
    const { refreshTodos } = mockUnifiedRefreshers();

    render(<TaskCenterRuntimeHost />);

    for (const status of ['pending', 'completed', 'cancelled'] as const) {
      useUnifiedTaskStore.setState({ todos: [{ id: 1, title: 't', status } as never] });
      refreshTodos.mockClear();
      await vi.advanceTimersByTimeAsync(SLOW_SOURCE_POLL_MS);
      expect(refreshTodos, `status=${status} 不应触发刷新`).not.toHaveBeenCalled();
    }
  });

  it('scheduled 轮询：存在 running 定时任务时按 30s 调用 refreshScheduled', async () => {
    vi.mocked(listShells).mockResolvedValue([]);
    const { refreshScheduled } = mockUnifiedRefreshers();
    useUnifiedTaskStore.setState({
      scheduledTasks: [{ id: 's1', name: 's', last_status: 'running' } as never],
    });

    render(<TaskCenterRuntimeHost />);
    await vi.advanceTimersByTimeAsync(SLOW_SOURCE_POLL_MS - 1);
    expect(refreshScheduled).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(refreshScheduled).toHaveBeenCalledTimes(1);
  });

  it('scheduled 轮询：无 running 定时任务时不调用 refreshScheduled', async () => {
    vi.mocked(listShells).mockResolvedValue([]);
    const { refreshScheduled } = mockUnifiedRefreshers();

    render(<TaskCenterRuntimeHost />);

    for (const lastStatus of ['never', 'succeeded', 'failed'] as const) {
      useUnifiedTaskStore.setState({
        scheduledTasks: [{ id: 's1', name: 's', last_status: lastStatus } as never],
      });
      refreshScheduled.mockClear();
      await vi.advanceTimersByTimeAsync(SLOW_SOURCE_POLL_MS);
      expect(refreshScheduled, `last_status=${lastStatus} 不应触发刷新`).not.toHaveBeenCalled();
    }
  });
});
