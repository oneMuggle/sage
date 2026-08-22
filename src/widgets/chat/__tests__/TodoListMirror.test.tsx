import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { TaskBoard } from '../../../features/send-message/useChat';
import type { TaskStatusEvent } from '../../../shared/api';
import { TodoListSection } from '../progress/TodoListSection';

function board(
  plan: TaskBoard['plan'],
  statuses: Record<string, Partial<TaskStatusEvent>> = {},
): TaskBoard {
  return {
    runId: 'orch-1',
    plan,
    statuses: statuses as TaskBoard['statuses'],
    dispatchedAt: Date.now(),
  };
}

function st(over: Partial<TaskStatusEvent>): TaskStatusEvent {
  return {
    state: 'task_status',
    run_id: 'orch-1',
    agent_id: 'a',
    goal: '',
    error: null,
    output_preview: null,
    ...over,
  } as TaskStatusEvent;
}

describe('TodoListSection orchestration mirror', () => {
  const PLAN = [
    { task_id: 't1', agent_id: 'researcher', goal: '搜集资料', depends_on: [] },
    { task_id: 't2', agent_id: 'writer', goal: '整理成文', depends_on: ['t1'] },
  ];

  it('mirrors plan items with badge and status glyph', () => {
    render(<TodoListSection todos={[]} taskBoard={board(PLAN)} />);
    expect(screen.getByTestId('todo-mirror-t1')).toHaveTextContent('搜集资料');
    expect(screen.getByTestId('todo-mirror-t1')).toHaveTextContent('编排');
    expect(screen.getByTestId('todo-mirror-t1')).toHaveTextContent('○'); // queued
  });

  it('follows status transitions', () => {
    const { rerender } = render(
      <TodoListSection
        todos={[]}
        taskBoard={board(PLAN, { t1: st({ task_id: 't1', status: 'running' }) })}
      />,
    );
    expect(screen.getByTestId('todo-mirror-t1')).toHaveTextContent('◐');

    rerender(
      <TodoListSection
        todos={[]}
        taskBoard={board(PLAN, { t1: st({ task_id: 't1', status: 'done' }) })}
      />,
    );
    expect(screen.getByTestId('todo-mirror-t1')).toHaveTextContent('☑');
  });

  it('renders agent todos before mirrored items', () => {
    render(
      <TodoListSection
        todos={[{ content: '自建任务', status: 'pending' }]}
        taskBoard={board(PLAN)}
      />,
    );
    const list = screen.getByTestId('todo-list');
    const firstIdx = list.innerHTML.indexOf('自建任务');
    const mirrorIdx = list.innerHTML.indexOf('todo-mirror-t1');
    expect(firstIdx).toBeGreaterThan(-1);
    expect(firstIdx).toBeLessThan(mirrorIdx);
  });

  it('indents mirrored items with dependencies', () => {
    render(<TodoListSection todos={[]} taskBoard={board(PLAN)} />);
    expect(screen.getByTestId('todo-mirror-t2')).toHaveClass('ml-4');
    expect(screen.getByTestId('todo-mirror-t1')).not.toHaveClass('ml-4');
  });

  it('no mirror without taskBoard', () => {
    render(
      <TodoListSection todos={[{ content: 'x', status: 'pending' }]} taskBoard={null} />,
    );
    expect(screen.queryByTestId('todo-mirror-t1')).toBeNull();
  });
});
