import { render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/api/shellApi', () => ({ listShells: vi.fn() }));

import { listShells } from '../../../shared/api/shellApi';
import { TaskCenterRuntimeHost } from '../TaskCenterRuntimeHost';
import { useTaskCenterStore } from '../taskCenterStore';
import { resetUnifiedTaskStore, useUnifiedTaskStore } from '../unifiedTaskStore';

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

  it('goal 轮询仅在存在非终态目标时继续', async () => {
    vi.mocked(listShells).mockResolvedValue([]);
    const refreshGoals = vi.spyOn(useUnifiedTaskStore.getState(), 'refreshGoals');
    useUnifiedTaskStore.setState({ goals: [{ id: 'g1', name: 'g', status: 'running' } as never] });

    render(<TaskCenterRuntimeHost />);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(refreshGoals).toHaveBeenCalled();

    useUnifiedTaskStore.setState({
      goals: [{ id: 'g1', name: 'g', status: 'completed' } as never],
    });
    refreshGoals.mockClear();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(refreshGoals).not.toHaveBeenCalled();
  });
});
