// RV3 (round8): TaskTreeSection 重跑失败任务按钮 —— run 终态且有失败任务时
// 显示，点击触发 onRerunFailed；进行中 / 无失败时隐藏。
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { TaskBoardState } from '../../../../features/send-message/chatStreamStore';
import { TaskTreeSection } from '../TaskTreeSection';

function makeBoard(overrides: Partial<TaskBoardState> = {}): TaskBoardState {
  return {
    runId: 'orch-rerun-ui',
    plan: [
      { task_id: 't1', goal: 'g1', agent_id: 'primary' },
      { task_id: 't2', goal: 'g2', agent_id: 'primary' },
    ] as TaskBoardState['plan'],
    statuses: {
      t1: {
        state: 'task_status',
        run_id: 'orch-rerun-ui',
        task_id: 't1',
        status: 'done',
        agent_id: 'primary',
        goal: 'g1',
        error: null,
        output_preview: null,
        retry_count: 0,
      },
      t2: {
        state: 'task_status',
        run_id: 'orch-rerun-ui',
        task_id: 't2',
        status: 'failed',
        agent_id: 'primary',
        goal: 'g2',
        error: 'boom',
        output_preview: null,
        retry_count: 0,
      },
    } as TaskBoardState['statuses'],
    progress: { total: 2, done: 1, running: 0, queued: 0, failed: 1, cancelled: 0 },
    dispatchedAt: Date.now(),
    ...overrides,
  };
}

describe('TaskTreeSection — rerun failed button (RV3)', () => {
  it('shows rerun button when run terminal and has failures; click fires callback', () => {
    const onRerunFailed = vi.fn();
    render(<TaskTreeSection board={makeBoard()} onRerunFailed={onRerunFailed} />);
    const btn = screen.getByTestId('task-tree-rerun-failed');
    fireEvent.click(btn);
    expect(onRerunFailed).toHaveBeenCalledTimes(1);
  });

  it('hides rerun button while tasks are still in flight', () => {
    const onRerunFailed = vi.fn();
    render(
      <TaskTreeSection
        board={makeBoard({
          progress: { total: 2, done: 1, running: 1, queued: 0, failed: 0, cancelled: 0 },
        })}
        onRerunFailed={onRerunFailed}
      />,
    );
    expect(screen.queryByTestId('task-tree-rerun-failed')).toBeNull();
  });

  it('hides rerun button when no failures', () => {
    render(
      <TaskTreeSection
        board={makeBoard({
          statuses: {
            t1: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't1',
              status: 'done',
              agent_id: 'primary',
              goal: 'g1',
              error: null,
              output_preview: null,
              retry_count: 0,
            },
            t2: {
              state: 'task_status',
              run_id: 'orch-rerun-ui',
              task_id: 't2',
              status: 'done',
              agent_id: 'primary',
              goal: 'g2',
              error: null,
              output_preview: null,
              retry_count: 0,
            },
          } as TaskBoardState['statuses'],
          progress: { total: 2, done: 2, running: 0, queued: 0, failed: 0, cancelled: 0 },
        })}
      />,
    );
    expect(screen.queryByTestId('task-tree-rerun-failed')).toBeNull();
  });
});
