import { act, renderHook } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { cancelLaneMock } = vi.hoisted(() => ({ cancelLaneMock: vi.fn() }));

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock('../../../shared/api/desktopInvoke', () => ({ invoke: vi.fn() }));
vi.mock('../../../entities/autonomous-goals/goalApi', () => ({
  cancelGoal: vi.fn(),
  pauseGoal: vi.fn(),
  startGoal: vi.fn(),
}));
vi.mock('../../../entities/orchestration/laneBoardStore', () => ({
  useLaneBoardStore: (selector: (state: { cancel: typeof cancelLaneMock }) => unknown) =>
    selector({ cancel: cancelLaneMock }),
}));
vi.mock('../../../shared/api/scheduledClient', () => ({
  scheduledClient: { runNow: vi.fn() },
}));
vi.mock('../../send-message/useChat', () => ({ cancelSessionStream: vi.fn() }));

import { cancelGoal, pauseGoal, startGoal } from '../../../entities/autonomous-goals/goalApi';
import { invoke } from '../../../shared/api/desktopInvoke';
import { scheduledClient } from '../../../shared/api/scheduledClient';
import { cancelSessionStream } from '../../send-message/useChat';
import { useTaskCenterStore } from '../taskCenterStore';
import type { UnifiedTaskEntry } from '../unifiedTaskModel';
import { useTaskCenterActions } from '../useTaskCenterActions';

const entry = (over: Partial<UnifiedTaskEntry>): UnifiedTaskEntry => ({
  id: 'goal:g1',
  source: 'goal',
  title: 'g',
  status: 'running',
  startedAt: 1,
  updatedAt: null,
  percent: null,
  error: null,
  cancellable: true,
  detailPath: '/goals/g1',
  openTarget: null,
  cancelRef: { source: 'goal', rawId: 'g1' },
  meta: {},
  ...over,
});

let probedPath = '';

const LocationProbe = () => {
  const location = useLocation();
  probedPath = `${location.pathname}${location.search}`;
  return null;
};

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <MemoryRouter>
    <LocationProbe />
    {children}
  </MemoryRouter>
);

describe('useTaskCenterActions', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    probedPath = '';
    // open() 会写 taskCenterStore 的抽屉状态，跨用例清理避免顺序耦合
    useTaskCenterStore.setState({ shellStream: null, delivery: null });
  });

  it('goal cancel 调 cancelGoal', async () => {
    vi.mocked(cancelGoal).mockResolvedValue({} as never);
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    await act(() => result.current.cancel(entry({})));
    expect(cancelGoal).toHaveBeenCalledWith('g1');
  });

  it('goal pause / resume 调 pauseGoal / startGoal', async () => {
    vi.mocked(pauseGoal).mockResolvedValue({} as never);
    vi.mocked(startGoal).mockResolvedValue({} as never);
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    await act(() => result.current.pause(entry({})));
    await act(() => result.current.resume(entry({})));
    expect(pauseGoal).toHaveBeenCalledWith('g1');
    expect(startGoal).toHaveBeenCalledWith('g1');
  });

  it('shell cancel 走 invoke(shell_kill)', async () => {
    vi.mocked(invoke).mockResolvedValue({} as never);
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    await act(() =>
      result.current.cancel(
        entry({
          id: 'registry:sh',
          source: 'registry',
          cancelRef: { source: 'registry', rawId: 'sh-9' },
          meta: { shellId: 'sh-9' },
        }),
      ),
    );
    expect(invoke).toHaveBeenCalledWith('shell_kill', { id: 'sh-9' });
  });

  it('lane cancel 调 laneBoardStore.cancel 并 await', async () => {
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    await act(() =>
      result.current.cancel(
        entry({
          id: 'lane:l1',
          source: 'lane',
          cancelRef: { source: 'lane', rawId: 'l1' },
        }),
      ),
    );
    expect(cancelLaneMock).toHaveBeenCalledWith('l1');
  });

  it('chat cancel 调 cancelSessionStream', async () => {
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    await act(() =>
      result.current.cancel(
        entry({
          id: 'chat:s1',
          source: 'chat',
          cancelRef: { source: 'chat', rawId: 's1' },
        }),
      ),
    );
    expect(cancelSessionStream).toHaveBeenCalledWith('s1');
  });

  it('scheduled runNow 调 scheduledClient.runNow', async () => {
    vi.mocked(scheduledClient.runNow).mockResolvedValue({} as never);
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    await act(() =>
      result.current.runNow(
        entry({
          id: 'scheduled:s1',
          source: 'scheduled',
          cancelRef: null,
        }),
      ),
    );
    expect(scheduledClient.runNow).toHaveBeenCalledWith('s1');
  });

  it('失败时 toast.error 且不抛出', async () => {
    vi.mocked(cancelGoal).mockRejectedValue(new Error('网络错误'));
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    await act(() => result.current.cancel(entry({})));
    expect(toast.error).toHaveBeenCalledWith('网络错误');
  });

  it('runNow / pause / resume 失败时 toast.error 且不抛出', async () => {
    vi.mocked(scheduledClient.runNow).mockRejectedValue(new Error('调度失败'));
    vi.mocked(pauseGoal).mockRejectedValue(new Error('暂停失败'));
    vi.mocked(startGoal).mockRejectedValue(new Error('恢复失败'));
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    await act(() =>
      result.current.runNow(entry({ id: 'scheduled:s1', source: 'scheduled', cancelRef: null })),
    );
    await act(() => result.current.pause(entry({})));
    await act(() => result.current.resume(entry({})));
    expect(toast.error).toHaveBeenCalledWith('调度失败');
    expect(toast.error).toHaveBeenCalledWith('暂停失败');
    expect(toast.error).toHaveBeenCalledWith('恢复失败');
  });

  it('不可取消的条目是空操作', async () => {
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    await act(() => result.current.cancel(entry({ cancellable: false, cancelRef: null })));
    expect(cancelGoal).not.toHaveBeenCalled();
    expect(invoke).not.toHaveBeenCalled();
  });

  // A4 / Phase 5 回归：旧的 TaskCenterWidget 有三条点击分支，删胶囊后必须保住
  it('open: shell 条目打开后台输出抽屉', () => {
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    act(() =>
      result.current.open(
        entry({
          id: 'registry:shell:sh-9',
          source: 'registry',
          detailPath: null,
          openTarget: { kind: 'shell', shellId: 'sh-9' },
        }),
      ),
    );
    expect(useTaskCenterStore.getState().shellStream).toBe('sh-9');
  });

  it('open: lane 待验收条目直开交付抽屉而非跳 /orchestration', () => {
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    act(() =>
      result.current.open(
        entry({
          id: 'lane:l1',
          source: 'lane',
          status: 'awaiting_approval',
          detailPath: '/orchestration',
          openTarget: { kind: 'lane-delivery', laneId: 'l1' },
        }),
      ),
    );
    expect(useTaskCenterStore.getState().delivery).toMatchObject({ kind: 'lane', laneId: 'l1' });
  });

  it('open: office 待验收条目直开交付抽屉', () => {
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    act(() =>
      result.current.open(
        entry({
          id: 'registry:r1',
          source: 'registry',
          status: 'awaiting_approval',
          detailPath: '/office',
          openTarget: { kind: 'office-delivery', entryId: 'r1' },
        }),
      ),
    );
    expect(useTaskCenterStore.getState().delivery).toMatchObject({ kind: 'office', entryId: 'r1' });
  });

  it('open: 普通条目走 detailPath 路由跳转', () => {
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    act(() => result.current.open(entry({ detailPath: '/goals/g1', openTarget: null })));
    expect(probedPath).toBe('/goals/g1');
    expect(useTaskCenterStore.getState().shellStream).toBeNull();
    expect(useTaskCenterStore.getState().delivery).toBeNull();
  });
});
