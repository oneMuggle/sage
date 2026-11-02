import { describe, expect, it } from 'vitest';

import { mapOrchestrationLanes, mapScheduledTasks } from '../pet/backgroundTasks';
import { mergeTaskReports } from '../pet/tasks';
import type { PetTaskReport } from '../pet/types';

const NOW = 1_700_000_000_000;

function lane(overrides: Record<string, unknown>) {
  return {
    lane_id: 'lane-1',
    task_id: 'task-1',
    agent_id: 'agent-1',
    status: 'running',
    created_at: NOW - 60_000,
    started_at: NOW - 50_000,
    completed_at: null,
    worktree: null,
    heartbeat: null,
    error: null,
    permission_preset: 'default',
    metadata: { source: 'planner', team_id: 'team-1', task_name: '抓取网页', goal: '整理竞品资料' },
    ...overrides,
  };
}

describe('mapOrchestrationLanes', () => {
  it('groups lanes per team into one report', () => {
    const reports = mapOrchestrationLanes(
      [
        lane({ lane_id: 'lane-1' }),
        lane({ lane_id: 'lane-2', metadata: { team_id: 'team-1', task_name: '写摘要' } }),
      ],
      NOW,
    );
    expect(reports).toHaveLength(1);
    expect(reports[0]).toMatchObject({
      id: 'orch:team-1',
      kind: 'orchestration',
      status: 'running',
      title: '整理竞品资料',
      runId: 'team-1',
    });
    expect(reports[0]?.phase).toBe('2 个任务');
    expect(reports[0]?.startedAt).toBe(NOW - 50_000);
  });

  it('maps blocked lanes to awaiting approval', () => {
    const reports = mapOrchestrationLanes([lane({ status: 'blocked' })], NOW);
    expect(reports[0]?.status).toBe('awaiting_approval');
  });

  it('shows recent failures but drops stale or finished-only groups', () => {
    const recent = mapOrchestrationLanes(
      [lane({ status: 'failed', completed_at: NOW - 60_000, error: 'boom' })],
      NOW,
    );
    expect(recent[0]).toMatchObject({ status: 'failed', error: 'boom', finishedAt: NOW - 60_000 });

    expect(
      mapOrchestrationLanes([lane({ status: 'failed', completed_at: NOW - 20 * 60_000 })], NOW),
    ).toEqual([]);
    expect(mapOrchestrationLanes([lane({ status: 'succeeded' })], NOW)).toEqual([]);
    expect(mapOrchestrationLanes([lane({ status: 'cancelled' })], NOW)).toEqual([]);
  });

  it('keeps a running lane even when an older lane in the same team failed', () => {
    const reports = mapOrchestrationLanes(
      [
        lane({ lane_id: 'old', status: 'failed', completed_at: NOW - 30 * 60_000 }),
        lane({ lane_id: 'new', status: 'running' }),
      ],
      NOW,
    );
    expect(reports).toHaveLength(1);
    expect(reports[0]?.status).toBe('running');
  });

  it('uses task names when no goal is present and falls back to the team id', () => {
    const names = mapOrchestrationLanes(
      [
        lane({ metadata: { team_id: 't2', task_name: 'A' } }),
        lane({ lane_id: 'b', metadata: { team_id: 't2', task_name: 'B' } }),
      ],
      NOW,
    );
    expect(names[0]?.title).toBe('A 等 2 个任务');

    const fallback = mapOrchestrationLanes([lane({ lane_id: 'lonely', metadata: {} })], NOW);
    expect(fallback[0]?.id).toBe('orch:lonely');
    expect(fallback[0]?.title).toBe('编排任务');
  });

  it('trusts the heartbeat only once it advances past the start time', () => {
    // Heartbeat advanced an hour after start, then went quiet 2h ago → stale.
    const staleHeartbeat = lane({
      lane_id: 'hb-stale',
      metadata: { team_id: 'team-hb-stale', goal: '心跳停了' },
      started_at: NOW - 3 * 60 * 60_000,
      created_at: NOW - 3 * 60 * 60_000,
      heartbeat: { last_ping_at: NOW - 2 * 60 * 60_000 },
    });
    expect(mapOrchestrationLanes([staleHeartbeat], NOW)).toEqual([]);

    const freshHeartbeat = lane({
      lane_id: 'hb-fresh',
      metadata: { team_id: 'team-hb-fresh', goal: '心跳正常' },
      started_at: NOW - 10 * 60_000,
      heartbeat: { last_ping_at: NOW - 60_000 },
    });
    expect(mapOrchestrationLanes([freshHeartbeat], NOW)[0]).toMatchObject({
      id: 'orch:team-hb-fresh',
      status: 'running',
    });
  });

  it('keeps long-running lanes when the heartbeat is static (backend not refreshing)', () => {
    const longRunning = lane({
      metadata: { team_id: 'team-long' },
      started_at: NOW - 2 * 60 * 60_000,
      created_at: NOW - 2 * 60 * 60_000,
      heartbeat: { last_ping_at: NOW - 2 * 60 * 60_000 },
    });
    expect(mapOrchestrationLanes([longRunning], NOW)[0]).toMatchObject({
      id: 'orch:team-long',
      status: 'running',
    });

    const abandoned = lane({
      metadata: { team_id: 'team-abandoned' },
      started_at: NOW - 12 * 24 * 60 * 60_000,
      created_at: NOW - 12 * 24 * 60 * 60_000,
      heartbeat: { last_ping_at: NOW - 12 * 24 * 60 * 60_000 },
    });
    expect(mapOrchestrationLanes([abandoned], NOW)).toEqual([]);
  });

  it('keeps lanes waiting on a human decision for up to a day', () => {
    const waiting = lane({
      status: 'blocked',
      metadata: { team_id: 'team-wait' },
      started_at: NOW - 3 * 60 * 60_000,
      created_at: NOW - 3 * 60 * 60_000,
      heartbeat: { last_ping_at: NOW - 3 * 60 * 60_000 },
    });
    expect(mapOrchestrationLanes([waiting], NOW)[0]).toMatchObject({
      id: 'orch:team-wait',
      status: 'awaiting_approval',
    });
  });

  it('keeps active lanes when timestamps are missing', () => {
    const noTimestamps = lane({
      metadata: { team_id: 'team-nots' },
      started_at: null,
      created_at: undefined,
      heartbeat: null,
    });
    expect(mapOrchestrationLanes([noTimestamps], NOW)[0]?.id).toBe('orch:team-nots');
  });

  it('drops queued lanes that were never started for more than a day', () => {
    const stale = lane({
      status: 'created',
      metadata: { team_id: 'team-q' },
      started_at: null,
      created_at: NOW - 48 * 60 * 60_000,
    });
    expect(mapOrchestrationLanes([stale], NOW)).toEqual([]);

    const fresh = lane({
      status: 'created',
      metadata: { team_id: 'team-q2' },
      started_at: null,
      created_at: NOW - 60_000,
    });
    expect(mapOrchestrationLanes([fresh], NOW)[0]).toMatchObject({
      id: 'orch:team-q2',
      status: 'queued',
    });
  });

  it('ignores malformed entries and unknown statuses', () => {
    expect(mapOrchestrationLanes([null, 1, 'x', { lane_id: 'a', status: 'bogus' }], NOW)).toEqual(
      [],
    );
    expect(mapOrchestrationLanes('nope', NOW)).toEqual([]);
  });
});

describe('mapScheduledTasks', () => {
  const failedTask = {
    id: 's1',
    name: '每日简报',
    session_id: 'session-1',
    last_attempt: NOW - 60_000,
    last_status: 'failed',
    last_error: 'delivery failed',
  };

  it('reports recent delivery failures with their target session', () => {
    const reports = mapScheduledTasks([failedTask], NOW);
    expect(reports).toEqual([
      {
        id: 'sched:s1',
        kind: 'scheduled',
        title: '每日简报',
        status: 'failed',
        phase: null,
        percent: null,
        sessionId: 'session-1',
        runId: null,
        error: 'delivery failed',
        startedAt: NOW - 60_000,
        finishedAt: NOW - 60_000,
      },
    ]);
  });

  it('drops old failures and non-failed tasks', () => {
    expect(mapScheduledTasks([{ ...failedTask, last_attempt: NOW - 20 * 60_000 }], NOW)).toEqual(
      [],
    );
    expect(mapScheduledTasks([{ ...failedTask, last_status: 'succeeded' }], NOW)).toEqual([]);
    expect(mapScheduledTasks([{ ...failedTask, last_status: 'never' }], NOW)).toEqual([]);
  });

  it('ignores malformed entries', () => {
    expect(mapScheduledTasks([{ id: 'x' }, null, 'x'], NOW)).toEqual([]);
    expect(mapScheduledTasks({}, NOW)).toEqual([]);
  });
});

describe('mergeTaskReports', () => {
  function report(id: string): PetTaskReport {
    return {
      id,
      kind: 'custom',
      title: id,
      status: 'running',
      phase: null,
      percent: null,
      sessionId: null,
      runId: null,
      error: null,
      startedAt: NOW,
      finishedAt: null,
    };
  }

  it('keeps primary entries on duplicate ids and honors the limit', () => {
    const merged = mergeTaskReports([report('a')], [report('a'), report('b'), report('c')], 2);
    expect(merged.map((task) => task.id)).toEqual(['a', 'b']);
  });

  it('handles empty inputs', () => {
    expect(mergeTaskReports([], [])).toEqual([]);
    expect(mergeTaskReports([report('a')], [])).toHaveLength(1);
  });
});
