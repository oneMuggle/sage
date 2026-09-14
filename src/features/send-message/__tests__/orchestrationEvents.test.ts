/**
 * orchestrationEvents — 编排/任务板事件应用器单测（R35）
 *
 * 验证 applyOrchestrationEventToBoard 把事件正确写入 chatStreamStore
 * 会话槽位：任务板建立/合并/进度聚合/复核/live 合成/approval_mode/
 * todo 快照/产物计数，以及跨 run 防串扰。
 */
import { beforeEach, describe, expect, it } from 'vitest';

import type { AgentEvent } from '../../../shared/api/types';
import {
  selectSessionSlots,
  useChatStreamStore,
} from '../chatStreamStore';
import { applyOrchestrationEventToBoard } from '../orchestrationEvents';

const SID = 'sess-r35';

const evt = (patch: Partial<AgentEvent>): AgentEvent =>
  ({
    state: 'task_plan',
    iteration: 0,
    session_id: SID,
    ...patch,
  }) as AgentEvent;

function slots() {
  return selectSessionSlots(useChatStreamStore.getState(), SID);
}

beforeEach(() => {
  useChatStreamStore.getState().clearStream(SID, 'nonexistent');
  useChatStreamStore.setState((prev) => {
    const streams = { ...prev } as Record<string, unknown>;
    // 直接清空该会话相关槽位（store 结构为 map）
    for (const k of Object.keys(streams)) {
      if (k.startsWith(SID)) delete streams[k];
    }
    return streams;
  });
});

describe('applyOrchestrationEventToBoard — R35', () => {
  it('task_plan 建立任务板', () => {
    const handled = applyOrchestrationEventToBoard(
      evt({
        state: 'task_plan',
        run_id: 'orch-1',
        plan: [{ task_id: 't1', agent_id: 'researcher', goal: 'G' }],
      }),
      SID,
    );
    expect(handled).toBe(true);
    const board = slots().taskBoard;
    expect(board?.runId).toBe('orch-1');
    expect(board?.plan).toHaveLength(1);
  });

  it('task_status 合并状态并聚合进度', () => {
    applyOrchestrationEventToBoard(
      evt({ state: 'task_plan', run_id: 'orch-2', plan: [{ task_id: 'a', agent_id: 'r', goal: 'GA' }, { task_id: 'b', agent_id: 'r', goal: 'GB' }] }),
      SID,
    );
    applyOrchestrationEventToBoard(
      evt({ state: 'task_status', run_id: 'orch-2', task_id: 'a', status: 'done' }),
      SID,
    );
    const board = slots().taskBoard!;
    expect(board.statuses['a']?.status).toBe('done');
    // total 聚合自 status 键数(与全路径口径一致), 而非 plan 长度
    expect(board.progress?.total).toBe(1);
    expect(board.progress?.done).toBe(1);
  });

  it('跨 run 的 task_status 不串扰', () => {
    applyOrchestrationEventToBoard(
      evt({ state: 'task_plan', run_id: 'orch-3', plan: [{ task_id: 'x', agent_id: 'r', goal: 'GX' }] }),
      SID,
    );
    applyOrchestrationEventToBoard(
      evt({ state: 'task_status', run_id: 'orch-OTHER', task_id: 'x', status: 'done' }),
      SID,
    );
    const board = slots().taskBoard!;
    expect(board.statuses['x']).toBeUndefined();
  });

  it('task_progress 覆盖 5 元组', () => {
    applyOrchestrationEventToBoard(
      evt({ state: 'task_plan', run_id: 'orch-4', plan: [{ task_id: 'x', agent_id: 'r', goal: 'GX' }] }),
      SID,
    );
    applyOrchestrationEventToBoard(
      evt({
        state: 'task_progress',
        run_id: 'orch-4',
        total: 3,
        done: 1,
        running: 1,
        queued: 1,
        failed: 0,
        cancelled: 0,
      }),
      SID,
    );
    expect(slots().taskBoard?.progress).toEqual({
      total: 3,
      done: 1,
      running: 1,
      queued: 1,
      failed: 0,
      cancelled: 0,
    });
  });

  it('subagent_event 合成轻量 agent 临时板', () => {
    const sid = 'sess-subagent'; // 独立会话避免前置用例的编排板泄漏
    applyOrchestrationEventToBoard(
      evt({
        state: 'subagent_event',
        run_id: 'agent-tmp1',
        task_id: 't1',
        agent_id: 'subagent',
        goal: '调研',
        phase: 'tool_call',
      }),
      sid,
    );
    const board = selectSessionSlots(useChatStreamStore.getState(), sid).taskBoard!;
    expect(board.runId).toBe('agent-tmp1');
    expect(board.plan?.[0]?.goal).toBe('调研');
    expect(board.live?.['t1']).toBeDefined();
  });

  it('approval_mode / todo_snapshot / artifact_created 被消费', () => {
    expect(
      applyOrchestrationEventToBoard(evt({ state: 'approval_mode', run_id: 'r1', mode: 'auto' }), SID),
    ).toBe(true);
    expect(
      applyOrchestrationEventToBoard(evt({ state: 'todo_snapshot', todos: [] }), SID),
    ).toBe(true);
    expect(
      applyOrchestrationEventToBoard(
        evt({
          state: 'artifact_created',
          artifact: { id: 'a', path: '/p', name: 'n', kind: 'file', size: 1, created_at: 1 },
        }),
        SID,
      ),
    ).toBe(true);
  });

  it('非编排事件返回 false（交还调用方处理）', () => {
    expect(applyOrchestrationEventToBoard(evt({ state: 'content_delta', content: 'x' }), SID)).toBe(
      false,
    );
    expect(applyOrchestrationEventToBoard(evt({ state: 'done', content: 'x' }), SID)).toBe(false);
  });
});
