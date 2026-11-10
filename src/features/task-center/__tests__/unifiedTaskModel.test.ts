import { describe, expect, it } from 'vitest';

import type { Goal } from '../../../entities/autonomous-goals/types';
import type { Lane, ScheduledTask, Todo } from '../../../shared/api/types';
import type { TaskCenterEntry } from '../taskCenterStore';
import {
  GOAL_STATUS_MAP,
  LANE_STATUS_MAP,
  SCHEDULED_STATUS_MAP,
  TODO_STATUS_MAP,
  compareUnifiedTasks,
  normalizeChatTask,
  normalizeGoalTask,
  normalizeLaneTask,
  normalizeRegistryTask,
  normalizeScheduledTask,
  normalizeTodoTask,
} from '../unifiedTaskModel';

describe('unifiedTaskModel / 状态映射表', () => {
  it('goal 六状态全覆盖，completed → succeeded', () => {
    expect(GOAL_STATUS_MAP).toEqual({
      pending: 'queued',
      running: 'running',
      paused: 'paused',
      completed: 'succeeded',
      failed: 'failed',
      cancelled: 'cancelled',
    });
  });

  it('todo 四状态全覆盖', () => {
    expect(TODO_STATUS_MAP).toEqual({
      pending: 'queued',
      in_progress: 'running',
      completed: 'succeeded',
      cancelled: 'cancelled',
    });
  });

  it('scheduled 四状态全覆盖', () => {
    expect(SCHEDULED_STATUS_MAP).toEqual({
      never: 'queued',
      running: 'running',
      succeeded: 'succeeded',
      failed: 'failed',
    });
  });

  it('lane 八状态全覆盖，blocked → awaiting_approval', () => {
    expect(LANE_STATUS_MAP).toEqual({
      created: 'queued',
      ready: 'queued',
      running: 'running',
      blocked: 'awaiting_approval',
      succeeded: 'succeeded',
      failed: 'failed',
      stopped: 'cancelled',
      cancelled: 'cancelled',
    });
  });
});

const makeGoal = (over: Partial<Goal> = {}): Goal => ({
  id: 'g1',
  name: '整理文献',
  description: '',
  status: 'pending',
  session_id: null,
  time_window: {
    off_peak_start: '00:00',
    off_peak_end: '06:00',
    weekends_off_peak: true,
    holidays: [],
    min_pricing_tier: 'standard',
    timezone: 'Asia/Shanghai',
  },
  // 必须与 src/entities/autonomous-goals/types.ts 的 ExecutionBudget 逐字一致
  budget: {
    max_rounds: 10,
    max_hours: 2,
    max_tokens: 1000,
    stop_on_failure: false,
  },
  checkpoints: [],
  current_round: 0,
  created_at: '2026-11-09T10:00:00',
  started_at: null,
  completed_at: null,
  total_tokens_used: 0,
  completion_percentage: 0,
  degradation_level: 'none',
  last_error: null,
  trigger_mode: 'conditional',
  execution_conditions: [],
  ...over,
});

describe('unifiedTaskModel / registry 归一', () => {
  it('普通 registry 任务：保留 percent / detailPath', () => {
    const entry: TaskCenterEntry = {
      id: 'r1',
      kind: 'office',
      title: '生成报告',
      startedAt: 1000,
      status: 'running',
      percent: 42,
      docName: 'report.docx',
    };
    const u = normalizeRegistryTask(entry);
    expect(u).toMatchObject({
      id: 'registry:r1',
      source: 'registry',
      title: '生成报告',
      status: 'running',
      startedAt: 1000,
      percent: 42,
      cancellable: false,
    });
    expect(u.meta.docName).toBe('report.docx');
  });

  it('shell 任务（kind=shell）：不可跳转、可取消、带 shellId', () => {
    const entry: TaskCenterEntry = {
      id: 'shell-1',
      kind: 'shell',
      title: 'npm test',
      startedAt: 2000,
      status: 'running',
      shellId: 'sh-9',
      exitCode: null,
    };
    const u = normalizeRegistryTask(entry);
    expect(u).toMatchObject({
      id: 'registry:shell-1',
      detailPath: null,
      cancellable: true,
    });
    expect(u.cancelRef).toEqual({ source: 'registry', rawId: 'sh-9' });
    expect(u.meta.shellId).toBe('sh-9');
  });

  it('已完成的 shell 任务不可取消', () => {
    const entry: TaskCenterEntry = {
      id: 'shell-2',
      kind: 'shell',
      title: 'done',
      startedAt: 1,
      status: 'succeeded',
      shellId: 'sh-1',
    };
    expect(normalizeRegistryTask(entry).cancellable).toBe(false);
  });
});

describe('unifiedTaskModel / chat 归一', () => {
  it('后台会话流恒为 running', () => {
    const u = normalizeChatTask({ sessionId: 's1', title: '后台对话', firstSeenAt: 500 });
    expect(u).toMatchObject({
      id: 'chat:s1',
      source: 'chat',
      status: 'running',
      startedAt: 500,
      detailPath: '/chat?session=s1',
      cancellable: true,
    });
  });
});

describe('unifiedTaskModel / lane 归一', () => {
  const lane = (over: Partial<Lane> = {}): Lane => ({
    lane_id: 'l1',
    task_id: 'T-1',
    agent_id: 'agent-a',
    status: 'running',
    created_at: 1,
    started_at: 2,
    completed_at: null,
    worktree: null,
    heartbeat: null,
    error: null,
    permission_preset: 'default',
    metadata: {},
    ...over,
  });

  it('可见 lane 归一为 running', () => {
    const u = normalizeLaneTask(lane());
    expect(u).toMatchObject({
      id: 'lane:l1',
      source: 'lane',
      status: 'running',
      startedAt: 2,
      cancellable: true,
      detailPath: '/orchestration',
    });
  });

  it('待验收 lane（succeeded 且未决议）→ awaiting_approval 且不可取消', () => {
    const u = normalizeLaneTask(lane({ status: 'succeeded' }));
    expect(u?.status).toBe('awaiting_approval');
    expect(u?.cancellable).toBe(false);
  });

  it('已决议 / 不可见 lane 不展示（返回 null）', () => {
    expect(
      normalizeLaneTask(lane({ status: 'succeeded', metadata: { accepted_at: 1 } })),
    ).toBeNull();
    expect(normalizeLaneTask(lane({ status: 'stopped' }))).toBeNull();
  });
});

describe('unifiedTaskModel / goal 归一', () => {
  it('pending 目标进入列表（闲时任务本体）', () => {
    const u = normalizeGoalTask(makeGoal());
    expect(u).toMatchObject({
      id: 'goal:g1',
      source: 'goal',
      title: '整理文献',
      status: 'queued',
      startedAt: null,
      detailPath: '/goals/g1',
      cancellable: true,
    });
    expect(u?.percent).toBe(0);
  });

  it('ISO 时间戳转 epoch ms', () => {
    const u = normalizeGoalTask(
      makeGoal({ started_at: '2026-11-09T10:00:00', status: 'running', completion_percentage: 40 }),
    );
    expect(u?.status).toBe('running');
    expect(u?.startedAt).toBe(Date.parse('2026-11-09T10:00:00'));
    expect(u?.percent).toBe(40);
  });

  it('completed → succeeded 且不可取消', () => {
    const u = normalizeGoalTask(makeGoal({ status: 'completed' }));
    expect(u?.status).toBe('succeeded');
    expect(u?.cancellable).toBe(false);
  });

  it('failed 保留 last_error', () => {
    const u = normalizeGoalTask(makeGoal({ status: 'failed', last_error: '模型超时' }));
    expect(u?.status).toBe('failed');
    expect(u?.error).toBe('模型超时');
  });
});

describe('unifiedTaskModel / todo 归一', () => {
  const todo = (over: Partial<Todo> = {}): Todo => ({
    id: 7,
    title: '写周报',
    status: 'in_progress',
    priority: 'medium',
    is_recurring: false,
    created_at: '2026-11-09T09:00:00',
    updated_at: '2026-11-09T09:30:00',
    ...over,
  });

  it('in_progress todo 进入列表', () => {
    const u = normalizeTodoTask(todo());
    expect(u).toMatchObject({
      id: 'todo:7',
      source: 'todo',
      status: 'running',
      detailPath: '/todos',
      cancellable: false,
    });
    expect(u?.updatedAt).toBe(Date.parse('2026-11-09T09:30:00'));
  });

  it('pending todo 不展示', () => {
    expect(normalizeTodoTask(todo({ status: 'pending' }))).toBeNull();
  });

  it('completed → succeeded；cancelled 不展示', () => {
    expect(normalizeTodoTask(todo({ status: 'completed' }))?.status).toBe('succeeded');
    expect(normalizeTodoTask(todo({ status: 'cancelled' }))).toBeNull();
  });
});

describe('unifiedTaskModel / scheduled 归一', () => {
  const task = (over: Partial<ScheduledTask> = {}): ScheduledTask => ({
    id: 'st1',
    name: '每日摘要',
    type: 'recurring',
    schedule: { kind: 'recurring', cron: '0 * * * *' },
    session_id: 's0',
    content: 'summary',
    enabled: true,
    last_status: 'running',
    created_at: 1_700_000_000_000,
    ...over,
  });

  it('running 进入列表', () => {
    const u = normalizeScheduledTask(task());
    expect(u).toMatchObject({
      id: 'scheduled:st1',
      source: 'scheduled',
      title: '每日摘要',
      status: 'running',
      detailPath: '/scheduled',
      cancellable: false,
    });
  });

  it('never / succeeded 不展示', () => {
    expect(normalizeScheduledTask(task({ last_status: 'never' }))).toBeNull();
    expect(normalizeScheduledTask(task({ last_status: 'succeeded' }))).toBeNull();
  });

  it('failed 展示并带 last_error', () => {
    const u = normalizeScheduledTask(task({ last_status: 'failed', last_error: 'boom' }));
    expect(u?.status).toBe('failed');
    expect(u?.error).toBe('boom');
  });
});

describe('unifiedTaskModel / 排序', () => {
  it('failed 排最前，同状态按 startedAt 升序，null 排最后', () => {
    const base = {
      source: 'registry' as const,
      updatedAt: null,
      percent: null,
      error: null,
      cancellable: false,
      detailPath: null,
      openTarget: null,
      cancelRef: null,
      meta: {},
    };
    const list = [
      { ...base, id: 'a', title: 'a', status: 'running' as const, startedAt: 30 },
      { ...base, id: 'b', title: 'b', status: 'failed' as const, startedAt: null },
      { ...base, id: 'c', title: 'c', status: 'running' as const, startedAt: 10 },
    ];
    expect([...list].sort(compareUnifiedTasks).map((e) => e.id)).toEqual(['b', 'c', 'a']);
  });
});
