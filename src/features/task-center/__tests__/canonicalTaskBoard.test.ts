import { describe, expect, it } from 'vitest';

import type { DirectoryRun, DirectoryTask } from '../../../shared/api/orchRunClient';
import { buildCanonicalTaskBoard } from '../canonicalTaskBoard';

const task = (over: Partial<DirectoryTask> = {}): DirectoryTask => ({
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

const run = (over: Partial<DirectoryRun> = {}): DirectoryRun => ({
  run_id: 'orch-1',
  session_id: 's1',
  status: 'running',
  created_at: 900,
  dispatched_at: 950,
  confirmed_at: 940,
  original_request: '整理文献并生成综述',
  final_summary: null,
  plan: [{ task_id: 't1', agent_id: 'researcher', goal: '搜集资料' }],
  tasks: [task()],
  ...over,
});

describe('canonicalTaskBoard / DirectoryRun 投影', () => {
  it('任务行投影为 task_status，runId/时间戳原样透传', () => {
    const board = buildCanonicalTaskBoard(run());

    expect(board.runId).toBe('orch-1');
    expect(board.dispatchedAt).toBe(950);
    expect(board.confirmedAt).toBe(940);
    expect(board.plan).toHaveLength(1);
    expect(board.statuses.t1).toMatchObject({
      state: 'task_status',
      run_id: 'orch-1',
      task_id: 't1',
      status: 'running',
      agent_id: 'researcher',
      goal: '搜集资料',
      error: null,
      output_preview: null,
    });
  });

  it('计划中尚无任务行的项按 queued 合成（已确认未落库窗口）', () => {
    const board = buildCanonicalTaskBoard(
      run({
        plan: [
          { task_id: 't1', agent_id: 'researcher', goal: '搜集资料' },
          { task_id: 't2', agent_id: 'writer', goal: '写初稿' },
        ],
      }),
    );

    expect(board.statuses.t2).toMatchObject({
      status: 'queued',
      agent_id: 'writer',
      goal: '写初稿',
      error: null,
      depth: 0,
    });
    expect(board.progress).toMatchObject({ total: 1, running: 1, queued: 0 });
  });

  it('plan 损坏（空数组）时用任务行兜底，保证任务树非空', () => {
    const board = buildCanonicalTaskBoard(run({ plan: [] }));
    expect(board.plan).toEqual([
      {
        task_id: 't1',
        agent_id: 'researcher',
        goal: '搜集资料',
        parent_task_id: null,
        depth: 0,
      },
    ]);
  });

  it('进度计数：paused 归入 queued，skipped/cancelled 单列', () => {
    const board = buildCanonicalTaskBoard(
      run({
        tasks: [
          task({ task_id: 'a', status: 'done' }),
          task({ task_id: 'b', status: 'failed' }),
          task({ task_id: 'c', status: 'cancelled' }),
          task({ task_id: 'd', status: 'skipped' }),
          task({ task_id: 'e', status: 'paused' }),
          task({ task_id: 'f', status: 'running' }),
        ],
      }),
    );

    expect(board.progress).toEqual({
      total: 6,
      done: 1,
      running: 1,
      queued: 1,
      failed: 1,
      cancelled: 1,
      skipped: 1,
    });
  });
});
