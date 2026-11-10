import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { useLaneBoardStore } from '../../../entities/orchestration/laneBoardStore';
import { useStore } from '../../../shared/lib/store';
import { useChatStreamStore } from '../../send-message/chatStreamStore';
import { useTaskCenterStore } from '../taskCenterStore';
import { resetUnifiedTaskStore, useUnifiedTaskStore } from '../unifiedTaskStore';
import { useUnifiedTasks } from '../useUnifiedTasks';

function resetAll(): void {
  useTaskCenterStore.setState({ tasks: {} });
  useChatStreamStore.setState({ sessions: {} });
  useLaneBoardStore.setState({ lanes: [] });
  useStore.setState({ sessions: [], currentSessionId: null } as never);
  resetUnifiedTaskStore();
}

describe('useUnifiedTasks', () => {
  beforeEach(resetAll);

  it('空态：全部分组为空、计数为 0', () => {
    const { result } = renderHook(() => useUnifiedTasks());
    expect(result.current.all).toEqual([]);
    expect(result.current.groups).toEqual({ active: [], failed: [], finished: [] });
    expect(result.current.attentionCount).toBe(0);
  });

  it('registry + goal + scheduled 三源合并并按状态分组', () => {
    useTaskCenterStore.setState({
      tasks: {
        r1: {
          id: 'r1',
          kind: 'office',
          title: '生成中',
          startedAt: 1,
          status: 'running',
        },
      },
    });
    useUnifiedTaskStore.setState({
      goals: [
        { id: 'g1', name: '闲时目标', status: 'pending', completion_percentage: 0 } as never,
        { id: 'g2', name: '失败目标', status: 'failed', last_error: 'boom' } as never,
      ],
      scheduledTasks: [
        { id: 's1', name: '定时失败', last_status: 'failed' } as never,
        { id: 's2', name: '历史成功', last_status: 'succeeded' } as never,
      ],
    });

    const { result } = renderHook(() => useUnifiedTasks());
    const ids = result.current.all.map((e) => e.id).sort();

    // s2（succeeded）按 spec §4.4 不进列表
    expect(ids).toEqual(['goal:g1', 'goal:g2', 'registry:r1', 'scheduled:s1']);

    expect(result.current.groups.failed.map((e) => e.id).sort()).toEqual([
      'goal:g2',
      'scheduled:s1',
    ]);
    expect(result.current.groups.active.map((e) => e.id).sort()).toEqual([
      'goal:g1',
      'registry:r1',
    ]);
    expect(result.current.groups.finished).toEqual([]);
  });

  it('attentionCount = 进行中 + 失败', () => {
    useTaskCenterStore.setState({
      tasks: {
        r1: { id: 'r1', kind: 'office', title: 'a', startedAt: 1, status: 'running' },
        r2: { id: 'r2', kind: 'office', title: 'b', startedAt: 1, status: 'failed' },
        r3: { id: 'r3', kind: 'office', title: 'c', startedAt: 1, status: 'paused' },
        r4: { id: 'r4', kind: 'office', title: 'd', startedAt: 1, status: 'succeeded' },
      },
    });
    const { result } = renderHook(() => useUnifiedTasks());
    expect(result.current.attentionCount).toBe(3); // running + failed + paused
  });

  it('后台会话流进入列表，当前会话被排除', () => {
    useStore.setState({
      sessions: [
        { id: 's-cur', title: '当前', created_at: 0, updated_at: 0 } as never,
        { id: 's-bg', title: '后台', created_at: 0, updated_at: 0 } as never,
      ],
      currentSessionId: 's-cur',
    } as never);
    useChatStreamStore.setState({
      sessions: {
        's-cur': { streaming: { startedAt: 1 } } as never,
        's-bg': { streaming: { startedAt: 2 } } as never,
      },
    });

    const { result } = renderHook(() => useUnifiedTasks());
    const chatIds = result.current.all.filter((e) => e.source === 'chat').map((e) => e.id);
    expect(chatIds).toEqual(['chat:s-bg']);
  });

  it('已决议 / 不可见 lane 不进入列表', () => {
    useLaneBoardStore.setState({
      lanes: [
        {
          lane_id: 'l1',
          task_id: 'T1',
          agent_id: null,
          status: 'running',
          created_at: 1,
          started_at: 1,
          completed_at: null,
          worktree: null,
          heartbeat: null,
          error: null,
          permission_preset: 'default',
          metadata: {},
        } as never,
        {
          lane_id: 'l2',
          task_id: 'T2',
          agent_id: null,
          status: 'stopped',
          created_at: 1,
          started_at: 1,
          completed_at: 2,
          worktree: null,
          heartbeat: null,
          error: null,
          permission_preset: 'default',
          metadata: {},
        } as never,
      ],
    });

    const { result } = renderHook(() => useUnifiedTasks());
    expect(result.current.all.filter((e) => e.source === 'lane').map((e) => e.id)).toEqual([
      'lane:l1',
    ]);
  });

  it('排序：failed 在最前', () => {
    useTaskCenterStore.setState({
      tasks: {
        r1: { id: 'r1', kind: 'office', title: 'ok', startedAt: 1, status: 'succeeded' },
        r2: { id: 'r2', kind: 'office', title: 'bad', startedAt: 2, status: 'failed' },
        r3: { id: 'r3', kind: 'office', title: 'run', startedAt: 3, status: 'running' },
      },
    });
    const { result } = renderHook(() => useUnifiedTasks());
    expect(result.current.all[0].id).toBe('registry:r2');
  });

  it('透传 store 的 loading / error', () => {
    useUnifiedTaskStore.setState({ loading: true, error: 'goal down' });
    const { result } = renderHook(() => useUnifiedTasks());
    expect(result.current.loading).toBe(true);
    expect(result.current.error).toBe('goal down');
  });

  it('todo 进入列表、终态归入 finished、待决议 lane 映射为 awaiting_approval', () => {
    useStore.setState({ currentSessionId: 's-other' } as never);
    useUnifiedTaskStore.setState({
      todos: [
        {
          id: 7,
          title: '买菜',
          status: 'in_progress',
          priority: 'medium',
          is_recurring: false,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        } as never,
      ],
    });
    useTaskCenterStore.setState({
      tasks: {
        'r-done': {
          id: 'r-done',
          kind: 'office',
          title: '已完成',
          startedAt: 1,
          status: 'succeeded',
        },
      },
    });
    useLaneBoardStore.setState({
      lanes: [
        {
          lane_id: 'l3',
          task_id: 'T3',
          agent_id: null,
          status: 'succeeded',
          created_at: 1,
          started_at: 1,
          completed_at: 2,
          worktree: null,
          heartbeat: null,
          error: null,
          permission_preset: 'default',
          metadata: {},
        } as never,
      ],
    });

    const { result } = renderHook(() => useUnifiedTasks());

    const todoEntry = result.current.all.find((e) => e.source === 'todo');
    expect(todoEntry?.title).toBe('买菜');

    expect(result.current.groups.finished.length).toBeGreaterThan(0);
    expect(result.current.groups.finished.map((e) => e.id)).toContain('registry:r-done');

    const laneEntry = result.current.all.find((e) => e.source === 'lane');
    expect(laneEntry?.status).toBe('awaiting_approval');
  });
});
