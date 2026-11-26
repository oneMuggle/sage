import { describe, expect, it } from 'vitest';

import type { Goal } from '../../../entities/autonomous-goals/types';
import type { DirectoryRun, DirectoryTask } from '../../../shared/api/orchRunClient';
import type { Lane, ScheduledTask, Todo } from '../../../shared/api/types';
import type { EvolutionRunSnapshot } from '../../../shared/api/types/domainEntityTypes';
import type { TaskCenterEntry } from '../taskCenterStore';
import {
  CANONICAL_RUN_STATUS_MAP,
  GOAL_STATUS_MAP,
  LANE_STATUS_MAP,
  SCHEDULED_STATUS_MAP,
  TODO_STATUS_MAP,
  canonicalRunProgress,
  compareUnifiedTasks,
  isCanonicalRunVisible,
  mergeSubagentEntries,
  normalizeCanonicalRun,
  normalizeCanonicalTask,
  normalizeChatTask,
  normalizeEvolutionRun,
  normalizeGoalTask,
  normalizeLaneTask,
  normalizeRegistryTask,
  normalizeScheduledTask,
  normalizeSubagentTask,
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

describe('unifiedTaskModel / M2.4 子代理任务', () => {
  const base = {
    sessionId: 's1',
    sessionTitle: '会话一',
    runId: 'run-1',
    taskId: 't1',
    agentId: 'researcher',
    goal: '搜集资料',
    liveStep: '🔧 read_file',
    waitingApproval: null,
    startedAt: 1,
    error: null,
  };

  it('running → 可定位子代理线程的任务中心条目', () => {
    const entry = normalizeSubagentTask({ ...base, status: 'running' });

    expect(entry).not.toBeNull();
    expect(entry!.id).toBe('subagent:s1:run-1:t1');
    expect(entry!.source).toBe('subagent');
    expect(entry!.status).toBe('running');
    expect(entry!.title).toBe('搜集资料');
    expect(entry!.detailPath).toBe('/chat?session=s1');
    expect(entry!.openTarget).toEqual({
      kind: 'subagent-thread',
      sessionId: 's1',
      runId: 'run-1',
      taskId: 't1',
    });
    expect(entry!.meta.liveStep).toBe('🔧 read_file');
  });

  it('等待审批 → awaiting_approval', () => {
    const entry = normalizeSubagentTask({
      ...base,
      status: 'running',
      waitingApproval: 'write_file',
    });
    expect(entry!.status).toBe('awaiting_approval');
  });

  it('failed 可见，done/cancelled/skipped 不进任务中心', () => {
    expect(normalizeSubagentTask({ ...base, status: 'failed' })!.status).toBe('failed');
    expect(normalizeSubagentTask({ ...base, status: 'done' })).toBeNull();
    expect(normalizeSubagentTask({ ...base, status: 'cancelled' })).toBeNull();
    expect(normalizeSubagentTask({ ...base, status: 'skipped' })).toBeNull();
  });
});

const makeDirectoryTask = (over: Partial<DirectoryTask> = {}): DirectoryTask => ({
  task_id: 't1',
  run_id: 'orch-1',
  agent_id: 'researcher',
  goal: '搜集资料',
  status: 'running',
  retry_count: 0,
  error: null,
  output_preview: null,
  started_at: 1000,
  finished_at: null,
  used_tokens: null,
  duration_ms: null,
  parent_task_id: null,
  depth: 0,
  retry_of: null,
  ...over,
});

const makeDirectoryRun = (over: Partial<DirectoryRun> = {}): DirectoryRun => ({
  run_id: 'orch-1',
  session_id: 's1',
  status: 'running',
  created_at: 900,
  dispatched_at: 950,
  confirmed_at: 940,
  original_request: '整理文献并生成综述',
  final_summary: null,
  plan: [{ task_id: 't1', agent_id: 'researcher', goal: '搜集资料' }],
  tasks: [makeDirectoryTask()],
  ...over,
});

describe('unifiedTaskModel / M4.2 canonical 运行视图', () => {
  it('run 状态映射四值全覆盖；run 行仅 running/failed 可见', () => {
    expect(CANONICAL_RUN_STATUS_MAP).toEqual({
      running: 'running',
      completed: 'succeeded',
      failed: 'failed',
      cancelled: 'cancelled',
    });
    expect(isCanonicalRunVisible('running')).toBe(true);
    expect(isCanonicalRunVisible('failed')).toBe(true);
    expect(isCanonicalRunVisible('completed')).toBe(false);
    expect(isCanonicalRunVisible('cancelled')).toBe(false);
  });

  it('canonical 子任务与内存行同 id，可自然去重合并', () => {
    const run = makeDirectoryRun();
    const entry = normalizeCanonicalTask(run, run.tasks[0]);

    expect(entry).not.toBeNull();
    expect(entry!.id).toBe('subagent:s1:orch-1:t1');
    expect(entry!.source).toBe('subagent');
    expect(entry!.status).toBe('running');
    expect(entry!.title).toBe('搜集资料');
    expect(entry!.startedAt).toBe(1000);
    expect(entry!.meta.retryCount).toBe(0);
    expect(entry!.meta.depth).toBe(0);
  });

  it('canonical 子任务：会话标题缺省用 sessionId 占位，终态不进任务中心', () => {
    const run = makeDirectoryRun();
    expect(normalizeCanonicalTask(run, run.tasks[0])!.meta.sessionTitle).toBe('s1');
    expect(normalizeCanonicalTask(run, run.tasks[0], '会话一')!.meta.sessionTitle).toBe('会话一');
    expect(normalizeCanonicalTask(run, makeDirectoryTask({ status: 'done' }))).toBeNull();
  });

  it('canonicalRunProgress：settled 覆盖 done/failed/cancelled/skipped，paused 单列', () => {
    const progress = canonicalRunProgress([
      makeDirectoryTask({ task_id: 'a', status: 'done' }),
      makeDirectoryTask({ task_id: 'b', status: 'done' }),
      makeDirectoryTask({ task_id: 'c', status: 'running' }),
      makeDirectoryTask({ task_id: 'd', status: 'queued' }),
      makeDirectoryTask({ task_id: 'e', status: 'paused' }),
      makeDirectoryTask({ task_id: 'f', status: 'failed' }),
      makeDirectoryTask({ task_id: 'g', status: 'cancelled' }),
      makeDirectoryTask({ task_id: 'h', status: 'skipped' }),
    ]);
    expect(progress).toEqual({
      total: 8,
      settled: 5,
      running: 1,
      queued: 1,
      paused: 1,
      failed: 1,
      percent: 63,
    });
    expect(canonicalRunProgress([]).percent).toBeNull();
  });

  it('run 级兜底行：无可见子任务时出现，可取消并定位右栏进度', () => {
    const run = makeDirectoryRun({
      tasks: [
        makeDirectoryTask({ task_id: 'a', status: 'done' }),
        makeDirectoryTask({ task_id: 'b', status: 'done' }),
      ],
    });
    const entry = normalizeCanonicalRun(run);

    expect(entry).not.toBeNull();
    expect(entry!.id).toBe('run:orch-1');
    expect(entry!.source).toBe('run');
    expect(entry!.status).toBe('running');
    expect(entry!.startedAt).toBe(950);
    expect(entry!.percent).toBe(100);
    expect(entry!.cancellable).toBe(true);
    expect(entry!.cancelRef).toEqual({ source: 'run', rawId: 'orch-1' });
    expect(entry!.openTarget).toEqual({
      kind: 'run-progress',
      sessionId: 's1',
      runId: 'orch-1',
    });
    expect(entry!.meta).toMatchObject({ taskCount: 2, settledCount: 2 });
  });

  it('run 级兜底行：有可见子任务/已结束 run 不出行（避免重复与噪音）', () => {
    expect(normalizeCanonicalRun(makeDirectoryRun())).toBeNull();
    expect(
      normalizeCanonicalRun(
        makeDirectoryRun({ status: 'completed', tasks: [makeDirectoryTask({ status: 'done' })] }),
      ),
    ).toBeNull();
  });

  it('failed run 兜底行不可取消，未派发时 startedAt 回退 created_at', () => {
    const entry = normalizeCanonicalRun(
      makeDirectoryRun({
        status: 'failed',
        dispatched_at: null,
        tasks: [makeDirectoryTask({ status: 'done' })],
      }),
    );
    expect(entry!.status).toBe('failed');
    expect(entry!.cancellable).toBe(false);
    expect(entry!.startedAt).toBe(900);
  });

  it('mergeSubagentEntries：canonical 定状态，内存补审批/liveStep/标题', () => {
    const run = makeDirectoryRun();
    const canonical = normalizeCanonicalTask(run, run.tasks[0])!;
    const memory = normalizeSubagentTask({
      sessionId: 's1',
      sessionTitle: '真实标题',
      runId: 'orch-1',
      taskId: 't1',
      agentId: 'researcher',
      goal: '搜集资料',
      status: 'running',
      liveStep: '🔧 read_file',
      waitingApproval: 'write_file',
      startedAt: 1000,
      error: null,
    })!;

    const merged = mergeSubagentEntries(canonical, memory);
    expect(merged.status).toBe('awaiting_approval');
    expect(merged.meta.sessionTitle).toBe('真实标题');
    expect(merged.meta.liveStep).toBe('🔧 read_file');
    expect(merged.meta.retryCount).toBe(0);
  });

  it('mergeSubagentEntries：canonical 终态压过内存旧状态', () => {
    const run = makeDirectoryRun({
      tasks: [makeDirectoryTask({ status: 'failed', error: '工具崩溃' })],
    });
    const canonical = normalizeCanonicalTask(run, run.tasks[0])!;
    const memory = normalizeSubagentTask({
      sessionId: 's1',
      sessionTitle: 's1',
      runId: 'orch-1',
      taskId: 't1',
      agentId: 'researcher',
      goal: '搜集资料',
      status: 'running',
      liveStep: null,
      waitingApproval: null,
      startedAt: 1000,
      error: null,
    })!;

    const merged = mergeSubagentEntries(canonical, memory);
    expect(merged.status).toBe('failed');
    expect(merged.error).toBe('工具崩溃');
  });
});

describe('normalizeEvolutionRun (2026-11-26 P1)', () => {
  const run = (over: Partial<EvolutionRunSnapshot> = {}): EvolutionRunSnapshot => ({
    run_id: 'run-1',
    name: 'memory_reflection',
    state: 'running',
    trigger: 'manual',
    phase: 'llm',
    phase_label: 'LLM 合并',
    progress: { llm_done: 3, llm_total: 6 },
    started_at: 1_700_000_000_000,
    finished_at: null,
    duration_ms: null,
    result: null,
    error: null,
    cancel_requested: false,
    ...over,
  });

  it('running：标题/进度百分比/可取消/深链', () => {
    const entry = normalizeEvolutionRun(run());
    expect(entry.id).toBe('evolution:memory_reflection');
    expect(entry.source).toBe('evolution');
    expect(entry.title).toBe('记忆整理');
    expect(entry.status).toBe('running');
    expect(entry.percent).toBe(50);
    expect(entry.cancellable).toBe(true);
    expect(entry.cancelRef).toEqual({ source: 'evolution', rawId: 'memory_reflection' });
    expect(entry.detailPath).toBe('/settings?tab=evolution');
    expect(entry.meta.phase).toBe('LLM 合并');
  });

  it('终态映射与不可取消', () => {
    expect(normalizeEvolutionRun(run({ state: 'succeeded', finished_at: 2 })).status).toBe(
      'succeeded',
    );
    const failed = normalizeEvolutionRun(run({ state: 'failed', error: 'boom' }));
    expect(failed.status).toBe('failed');
    expect(failed.error).toBe('boom');

    const cancelled = normalizeEvolutionRun(run({ state: 'cancelled' }));
    expect(cancelled.status).toBe('cancelled');
    expect(cancelled.cancellable).toBe(false);
    expect(cancelled.cancelRef).toBeNull();
    expect(cancelled.percent).toBeNull();
  });

  it('无 llm_total 时 percent 为 null（不伪造进度）', () => {
    expect(normalizeEvolutionRun(run({ progress: {} })).percent).toBeNull();
  });
});
