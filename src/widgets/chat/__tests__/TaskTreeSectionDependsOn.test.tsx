// src/widgets/chat/__tests__/TaskTreeSectionDependsOn.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { TaskBoard } from '../../../features/send-message/useChat';
import { TaskTreeSection } from '../progress/TaskTreeSection';

function makeBoard(plan: TaskBoard['plan']): TaskBoard {
  return { runId: 'orch-1', plan, statuses: {} };
}

describe('TaskTreeSection depends_on (P1-6)', () => {
  it('renders depends_on as indentation marker + deps row', () => {
    const board = makeBoard([
      { task_id: 't1', agent_id: 'primary', goal: 'g1' },
      { task_id: 't2', agent_id: 'writer', goal: 'g2', depends_on: ['t1'] },
    ]);
    render(<TaskTreeSection board={board} />);
    // t2 有依赖 → 缩进 ml-4 + deps 标记行
    expect(screen.getByTestId('task-tree-item-t2')).toHaveClass('ml-4');
    expect(screen.getByTestId('task-tree-deps-t2')).toHaveTextContent('↳ 依赖 t1');
    // t1 无依赖 → 无缩进、无 deps 行
    expect(screen.getByTestId('task-tree-item-t1')).not.toHaveClass('ml-4');
    expect(screen.queryByTestId('task-tree-deps-t1')).toBeNull();
  });

  it('renders without indentation when no depends_on present', () => {
    const board = makeBoard([{ task_id: 't1', agent_id: 'primary', goal: 'g1' }]);
    render(<TaskTreeSection board={board} />);
    expect(screen.getByTestId('task-tree-item-t1')).not.toHaveClass('ml-4');
    expect(screen.queryByTestId('task-tree-deps-t1')).toBeNull();
  });

  it('joins multiple dependencies with comma', () => {
    const board = makeBoard([
      { task_id: 't3', agent_id: 'writer', goal: 'g3', depends_on: ['t1', 't2'] },
    ]);
    render(<TaskTreeSection board={board} />);
    expect(screen.getByTestId('task-tree-deps-t3')).toHaveTextContent('↳ 依赖 t1, t2');
  });

  it('tolerates plan items missing depends_on (backward compat)', () => {
    // 老 run 的 task_plan 无 depends_on 字段 → 不 crash,正常渲染 goal
    const board = makeBoard([{ task_id: 't1', agent_id: 'researcher', goal: '搜集资料' }]);
    render(<TaskTreeSection board={board} />);
    expect(screen.getByText('搜集资料')).toBeInTheDocument();
  });
});
