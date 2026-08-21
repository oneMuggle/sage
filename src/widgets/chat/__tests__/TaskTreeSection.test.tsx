import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { TaskBoard } from '../../../features/send-message/useChat';
import { TaskTreeSection } from '../progress/TaskTreeSection';

function makeBoard(overrides: Partial<TaskBoard> = {}): TaskBoard {
  return {
    runId: 'orch-1',
    plan: [
      { task_id: 't1', agent_id: 'researcher', goal: '搜集资料' },
      { task_id: 't2', agent_id: 'writer', goal: '整理学习资料' },
    ],
    statuses: {},
    ...overrides,
  };
}

describe('TaskTreeSection', () => {
  it('renders plan rows with agent badges and goals', () => {
    render(<TaskTreeSection board={makeBoard()} />);
    expect(screen.getByText('researcher')).toBeInTheDocument();
    expect(screen.getByText('writer')).toBeInTheDocument();
    expect(screen.getByText('搜集资料')).toBeInTheDocument();
    expect(screen.getByText('整理学习资料')).toBeInTheDocument();
  });

  it('shows completion summary', () => {
    const board = makeBoard({
      statuses: {
        t1: {
          state: 'task_status',
          run_id: 'orch-1',
          task_id: 't1',
          status: 'done',
          agent_id: 'researcher',
          goal: '搜集资料',
          error: null,
          output_preview: '完成',
        },
      },
    });
    render(<TaskTreeSection board={board} />);
    // 进度可视化 P0-2 (2026-08-12): 头条文案 + 完成计数,取代旧 "子任务 1/2 完成"
    expect(screen.getByText(/完成 1\/2/)).toBeInTheDocument();
    expect(screen.getByText(/已拆解为 2 个子任务/)).toBeInTheDocument();
  });

  it('renders running spinner for in-flight task', () => {
    const board = makeBoard({
      statuses: {
        t1: {
          state: 'task_status',
          run_id: 'orch-1',
          task_id: 't1',
          status: 'running',
          agent_id: 'researcher',
          goal: '搜集资料',
          error: null,
          output_preview: null,
        },
      },
    });
    render(<TaskTreeSection board={board} />);
    expect(screen.getByTitle('running')).toBeInTheDocument();
  });

  it('shows output_preview expandable for done task', () => {
    const board = makeBoard({
      statuses: {
        t1: {
          state: 'task_status',
          run_id: 'orch-1',
          task_id: 't1',
          status: 'done',
          agent_id: 'researcher',
          goal: '搜集资料',
          error: null,
          output_preview: '调研结论摘要',
        },
      },
    });
    render(<TaskTreeSection board={board} />);
    expect(screen.getByText('调研结论摘要')).toBeInTheDocument();
  });

  it('plan row without status falls back to queued', () => {
    render(<TaskTreeSection board={makeBoard()} />);
    expect(screen.getAllByTitle('queued')).toHaveLength(2);
  });

  // 进度可视化 P0-2 (2026-08-12): 5 元组快照渲染
  it('shows in-flight and failed counts from progress snapshot', () => {
    const board = makeBoard({
      statuses: {
        t1: {
          state: 'task_status',
          run_id: 'orch-1',
          task_id: 't1',
          status: 'done',
          agent_id: 'researcher',
          goal: '搜集资料',
          error: null,
          output_preview: null,
        },
      },
      progress: {
        total: 3,
        done: 1,
        running: 1,
        queued: 1,
        failed: 0,
      },
    });
    render(<TaskTreeSection board={board} />);
    expect(screen.getByText(/完成 1\/3/)).toBeInTheDocument();
    // 2 个进行中 (running + queued)
    expect(screen.getByText(/2 个进行中/)).toBeInTheDocument();
  });

  it('shows failed count when failures present', () => {
    const board = makeBoard({
      progress: { total: 2, done: 0, running: 0, queued: 0, failed: 1 },
    });
    render(<TaskTreeSection board={board} />);
    expect(screen.getByText(/\(1 失败\)/)).toBeInTheDocument();
  });

  // Wave 3 H2 (2026-08-15): 运行中编排的取消按钮
  it('shows cancel button while in-flight and fires onCancel', () => {
    const onCancel = vi.fn();
    const board = makeBoard({
      statuses: {
        t1: {
          state: 'task_status',
          run_id: 'orch-1',
          task_id: 't1',
          status: 'running',
          agent_id: 'researcher',
          goal: '搜集资料',
          error: null,
          output_preview: null,
        },
      },
    });
    render(<TaskTreeSection board={board} onCancel={onCancel} />);
    expect(screen.getByTestId('task-tree-cancel')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('task-tree-cancel'));
    expect(onCancel).toHaveBeenCalled();
  });

  it('hides cancel button when all done', () => {
    const board = makeBoard({
      statuses: {
        t1: {
          state: 'task_status',
          run_id: 'orch-1',
          task_id: 't1',
          status: 'done',
          agent_id: 'researcher',
          goal: '搜集资料',
          error: null,
          output_preview: null,
        },
        t2: {
          state: 'task_status',
          run_id: 'orch-1',
          task_id: 't2',
          status: 'done',
          agent_id: 'writer',
          goal: '整理学习资料',
          error: null,
          output_preview: null,
        },
      },
    });
    render(<TaskTreeSection board={board} onCancel={vi.fn()} />);
    expect(screen.queryByTestId('task-tree-cancel')).toBeNull();
  });

  it('hides cancel button when onCancel not provided', () => {
    render(<TaskTreeSection board={makeBoard()} />);
    expect(screen.queryByTestId('task-tree-cancel')).toBeNull();
  });

  it('renders cancelled status icon for cancelled tasks', () => {
    const board = makeBoard({
      statuses: {
        t1: {
          state: 'task_status',
          run_id: 'orch-1',
          task_id: 't1',
          status: 'cancelled',
          agent_id: 'researcher',
          goal: '搜集资料',
          error: 'cancelled by user',
          output_preview: null,
        },
      },
    });
    render(<TaskTreeSection board={board} />);
    expect(screen.getByTestId('task-tree-item-t1')).toHaveTextContent('⊘');
  });

  // P0-6 (2026-08-20): reviewer 复核结论横幅 —— pass/fail 双色展示
  it('shows review pass banner with assertion count', () => {
    const board = makeBoard({
      review: {
        state: 'task_review',
        run_id: 'orch-1',
        task_id: 't1',
        reviewer_id: 'reviewer',
        verdict: 'pass',
        assertion_count: 4,
        summary: '全部通过',
      },
    });
    render(<TaskTreeSection board={board} />);
    const banner = screen.getByTestId('task-review-banner');
    expect(banner).toHaveTextContent('复核通过');
    expect(banner).toHaveTextContent('4');
  });

  it('shows review fail banner with summary', () => {
    const board = makeBoard({
      review: {
        state: 'task_review',
        run_id: 'orch-1',
        task_id: 't1',
        reviewer_id: 'reviewer',
        verdict: 'fail',
        assertion_count: 3,
        summary: '结论缺少数据支撑',
      },
    });
    render(<TaskTreeSection board={board} />);
    const banner = screen.getByTestId('task-review-banner');
    expect(banner).toHaveTextContent('复核存疑');
    expect(banner).toHaveTextContent('结论缺少数据支撑');
  });
});
