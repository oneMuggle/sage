import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { TaskBoard } from '../../../features/send-message/useChat';
import { TaskTreeSection } from '../progress/TaskTreeSection';
import { buildTaskTree, descendantsOf } from '../progress/taskTree';

function makeBoard(plan: TaskBoard['plan']): TaskBoard {
  return {
    runId: 'orch-1',
    plan,
    statuses: {},
    progress: {
      total: plan.length,
      done: 0,
      running: 0,
      queued: plan.length,
      failed: 0,
      cancelled: 0,
    },
  };
}

describe('buildTaskTree', () => {
  it('indexes parent/child relationships and depths', () => {
    const index = buildTaskTree([
      { task_id: 't1', agent_id: 'a', goal: 'root' },
      { task_id: 't2', agent_id: 'b', goal: 'child', parent_task_id: 't1' },
      {
        task_id: 't3',
        agent_id: 'c',
        goal: 'grand',
        parent_task_id: 't2',
      },
    ]);

    expect(index.roots).toEqual(['t1']);
    expect(index.nodes.get('t1')!.childIds).toEqual(['t2']);
    expect(index.nodes.get('t2')!.depth).toBe(1);
    expect(index.nodes.get('t3')!.depth).toBe(2);
  });

  it('treats tasks with missing parents as roots', () => {
    const index = buildTaskTree([
      { task_id: 't1', agent_id: 'a', goal: 'orphan', parent_task_id: 'nope' },
    ]);
    expect(index.roots).toEqual(['t1']);
    expect(index.nodes.get('t1')!.depth).toBe(0);
  });

  it('keeps legacy plans flat', () => {
    const index = buildTaskTree([
      { task_id: 't1', agent_id: 'a', goal: 'one' },
      { task_id: 't2', agent_id: 'b', goal: 'two' },
    ]);
    expect(index.roots).toEqual(['t1', 't2']);
    expect(index.nodes.get('t1')!.depth).toBe(0);
    expect(index.nodes.get('t2')!.depth).toBe(0);
  });

  it('does not drop tasks when the parent chain cycles', () => {
    const index = buildTaskTree([
      { task_id: 't1', agent_id: 'a', goal: 'one', parent_task_id: 't2' },
      { task_id: 't2', agent_id: 'b', goal: 'two', parent_task_id: 't1' },
    ]);
    const visible = [...index.nodes.keys()].sort();
    expect(visible).toEqual(['t1', 't2']);
  });
});

describe('descendantsOf', () => {
  it('returns all transitive children', () => {
    const index = buildTaskTree([
      { task_id: 't1', agent_id: 'a', goal: 'root' },
      { task_id: 't2', agent_id: 'b', goal: 'child', parent_task_id: 't1' },
      { task_id: 't3', agent_id: 'c', goal: 'grand', parent_task_id: 't2' },
    ]);
    expect(descendantsOf(index, 't1').sort()).toEqual(['t2', 't3']);
    expect(descendantsOf(index, 't3')).toEqual([]);
  });
});

describe('TaskTreeSection hierarchy', () => {
  it('indents child tasks and exposes depth', () => {
    render(
      <TaskTreeSection
        board={makeBoard([
          { task_id: 't1', agent_id: 'a', goal: 'root' },
          { task_id: 't2', agent_id: 'b', goal: 'child', parent_task_id: 't1' },
        ])}
      />,
    );

    expect(screen.getByTestId('task-tree-item-t1')).toHaveAttribute(
      'data-depth',
      '0',
    );
    expect(screen.getByTestId('task-tree-item-t2')).toHaveAttribute(
      'data-depth',
      '1',
    );
  });

  it('collapses and expands descendants', () => {
    render(
      <TaskTreeSection
        board={makeBoard([
          { task_id: 't1', agent_id: 'a', goal: 'root' },
          { task_id: 't2', agent_id: 'b', goal: 'child', parent_task_id: 't1' },
        ])}
      />,
    );

    expect(screen.getByTestId('task-tree-item-t2')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('task-tree-toggle-t1'));
    expect(screen.queryByTestId('task-tree-item-t2')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('task-tree-toggle-t1'));
    expect(screen.getByTestId('task-tree-item-t2')).toBeInTheDocument();
  });

  it('renders legacy plans without toggles', () => {
    render(
      <TaskTreeSection
        board={makeBoard([
          { task_id: 't1', agent_id: 'a', goal: 'one' },
          { task_id: 't2', agent_id: 'b', goal: 'two' },
        ])}
      />,
    );
    expect(screen.queryByTestId('task-tree-toggle-t1')).not.toBeInTheDocument();
    expect(screen.getByTestId('task-tree-item-t2')).toHaveAttribute(
      'data-depth',
      '0',
    );
  });
});
