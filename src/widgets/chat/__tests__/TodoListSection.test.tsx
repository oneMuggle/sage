import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { TodoItem } from '../../../shared/api';
import { TodoListSection } from '../progress/TodoListSection';

const TODOS: TodoItem[] = [
  { content: '调研方案', status: 'completed' },
  { content: '写实现', status: 'in_progress', activeForm: '正在写实现' },
  { content: '补测试', status: 'pending' },
];

describe('TodoListSection', () => {
  it('renders all items with status glyphs', () => {
    render(<TodoListSection todos={TODOS} />);
    expect(screen.getByTestId('todo-list')).toBeInTheDocument();
    expect(screen.getByText('调研方案')).toBeInTheDocument();
    expect(screen.getByText('写实现')).toBeInTheDocument();
    expect(screen.getByText('补测试')).toBeInTheDocument();
    expect(screen.getByTestId('todo-item-0')).toHaveTextContent('☑');
    expect(screen.getByTestId('todo-item-1')).toHaveTextContent('◐');
    expect(screen.getByTestId('todo-item-2')).toHaveTextContent('○');
  });

  it('shows progress counter', () => {
    render(<TodoListSection todos={TODOS} />);
    expect(screen.getByTestId('todo-progress')).toHaveTextContent('1/3');
  });

  it('renders nothing when empty', () => {
    const { container } = render(<TodoListSection todos={[]} />);
    expect(container.querySelector('[data-testid="todo-list"]')).toBeNull();
  });

  it('marks in_progress item with active label', () => {
    render(
      <TodoListSection
        todos={[{ content: '写实现', status: 'in_progress', activeForm: '正在写实现' }]}
      />,
    );
    expect(screen.getByText(/正在写实现/)).toBeInTheDocument();
  });
});
