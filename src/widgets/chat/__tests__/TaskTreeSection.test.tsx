import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TaskTreeSection } from '../progress/TaskTreeSection';
import type { TaskBoard } from '../../../features/send-message/useChat';

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
        t1: { state: 'task_status', run_id: 'orch-1', task_id: 't1', status: 'done', agent_id: 'researcher', goal: '搜集资料', error: null, output_preview: '完成' },
      },
    });
    render(<TaskTreeSection board={board} />);
    expect(screen.getByText(/子任务 1\/2 完成/)).toBeInTheDocument();
  });

  it('renders running spinner for in-flight task', () => {
    const board = makeBoard({
      statuses: {
        t1: { state: 'task_status', run_id: 'orch-1', task_id: 't1', status: 'running', agent_id: 'researcher', goal: '搜集资料', error: null, output_preview: null },
      },
    });
    render(<TaskTreeSection board={board} />);
    expect(screen.getByTitle('running')).toBeInTheDocument();
  });

  it('shows output_preview expandable for done task', () => {
    const board = makeBoard({
      statuses: {
        t1: { state: 'task_status', run_id: 'orch-1', task_id: 't1', status: 'done', agent_id: 'researcher', goal: '搜集资料', error: null, output_preview: '调研结论摘要' },
      },
    });
    render(<TaskTreeSection board={board} />);
    expect(screen.getByText('调研结论摘要')).toBeInTheDocument();
  });

  it('plan row without status falls back to queued', () => {
    render(<TaskTreeSection board={makeBoard()} />);
    expect(screen.getAllByTitle('queued')).toHaveLength(2);
  });
});
