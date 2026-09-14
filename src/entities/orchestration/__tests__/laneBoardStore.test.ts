/**
 * laneBoardStore — board 降级分支直接单测。
 *
 * 覆盖 load() 的三条路径（降级铁律的前端对应物）：
 * 1. getBoard reject + listLanes 成功 → lanes 正常渲染、boardSummary === null；
 * 2. listLanes reject → error 置位、lanes 空；
 * 3. load 成功 → boardSummary 来自 ops_full 快照的 freshness_summary。
 *
 * Mock 在 desktopInvoke 接缝（与 Orchestration.test.tsx 同模式），
 * 走真实的 orchestrationClient + laneBoardStore 流程。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: vi.fn(),
}));

import { invoke } from '../../../shared/api/desktopInvoke';
import type { FreshnessSummaryInfo, Lane } from '../../../shared/api/types';
import { useLaneBoardStore } from '../laneBoardStore';

const invokeMock = invoke as unknown as ReturnType<typeof vi.fn>;

function makeLane(overrides: Partial<Lane> = {}): Lane {
  return {
    lane_id: 'lane-1',
    task_id: 'task-1',
    agent_id: 'researcher',
    status: 'created',
    created_at: 0,
    started_at: null,
    completed_at: null,
    worktree: null,
    heartbeat: null,
    error: null,
    permission_preset: 'implement',
    metadata: { source: 'planner' },
    ...overrides,
  };
}

describe('laneBoardStore.load()', () => {
  afterEach(() => {
    invokeMock.mockReset();
  });

  it('board 拉取失败 → boardSummary 置 null，lanes 正常渲染', async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'orchestration_board') {
        throw new Error('board down');
      }
      return [makeLane()];
    });
    useLaneBoardStore.setState({ lanes: [], boardSummary: null, error: null, loading: false });

    await useLaneBoardStore.getState().load();

    const { lanes, boardSummary, error, loading } = useLaneBoardStore.getState();
    expect(lanes).toHaveLength(1);
    expect(boardSummary).toBeNull();
    expect(error).toBeNull();
    expect(loading).toBe(false);
  });

  it('listLanes 失败 → error 置位、lanes 为空', async () => {
    invokeMock.mockRejectedValueOnce(new Error('lanes down'));
    useLaneBoardStore.setState({ lanes: [], boardSummary: null, error: null, loading: false });

    await useLaneBoardStore.getState().load('team-1');

    const { lanes, boardSummary, error, loading } = useLaneBoardStore.getState();
    expect(lanes).toEqual([]);
    expect(error).toBe('lanes down');
    expect(boardSummary).toBeNull();
    expect(loading).toBe(false);
  });

  it('load 成功 → boardSummary 来自快照 freshness_summary', async () => {
    const summary: FreshnessSummaryInfo = {
      total: 2,
      fresh: 1,
      stale: 1,
      dead: 0,
      overall_level: 'stale',
    };
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'orchestration_board') {
        return {
          schema_version: '1.0',
          generated_at: 1758500000000,
          generated_by: 'http-api',
          active: [],
          blocked: [],
          finished: [],
          freshness_summary: summary,
        };
      }
      return [makeLane(), makeLane({ lane_id: 'lane-2' })];
    });
    useLaneBoardStore.setState({ lanes: [], boardSummary: null, error: null, loading: false });

    await useLaneBoardStore.getState().load();

    const { lanes, boardSummary, error } = useLaneBoardStore.getState();
    expect(lanes).toHaveLength(2);
    expect(boardSummary).toEqual(summary);
    expect(error).toBeNull();
  });
});

describe('laneBoardStore.decide() (A4)', () => {
  afterEach(() => {
    invokeMock.mockReset();
  });

  it('accept 成功 → 透传 decision 负载并用返回 lane 替换卡片', async () => {
    const before = makeLane({ status: 'succeeded', metadata: { acceptance_pending: true } });
    const after = makeLane({
      status: 'succeeded',
      metadata: { acceptance_pending: false, accepted_at: 1759000000000 },
    });
    const fixture = {
      ok: true,
      lane: after,
      decision: 'accept',
      merged: true,
      already: false,
      warning: null,
      merge: { code: 'merged', branch: 'lane/accept/lane-1-ab12cd34' },
    };
    invokeMock.mockResolvedValueOnce(fixture);
    useLaneBoardStore.setState({ lanes: [before], error: null });

    const result = await useLaneBoardStore.getState().decide('lane-1', 'accept', 'looks good');

    expect(invokeMock).toHaveBeenCalledWith('orchestration_lane_decision', {
      lane_id: 'lane-1',
      decision: 'accept',
      reason: 'looks good',
    });
    expect(result).toEqual(fixture);
    expect(useLaneBoardStore.getState().lanes).toEqual([after]);
    expect(useLaneBoardStore.getState().error).toBeNull();
  });

  it('reject 缺省 reason 为空串', async () => {
    const lane = makeLane({ status: 'succeeded' });
    invokeMock.mockResolvedValueOnce({
      ok: true,
      lane,
      decision: 'reject',
      merged: false,
      already: false,
      warning: null,
      merge: null,
    });
    useLaneBoardStore.setState({ lanes: [lane], error: null });

    await useLaneBoardStore.getState().decide('lane-1', 'reject');

    expect(invokeMock).toHaveBeenCalledWith('orchestration_lane_decision', {
      lane_id: 'lane-1',
      decision: 'reject',
      reason: '',
    });
  });

  it('失败 → error 置位并向调用方抛错，lane 不变', async () => {
    const lane = makeLane({ status: 'succeeded' });
    invokeMock.mockRejectedValueOnce(new Error('conflict'));
    useLaneBoardStore.setState({ lanes: [lane], error: null });

    await expect(useLaneBoardStore.getState().decide('lane-1', 'accept')).rejects.toThrow(
      'conflict',
    );
    expect(useLaneBoardStore.getState().error).toBe('conflict');
    expect(useLaneBoardStore.getState().lanes).toEqual([lane]);
  });
});

