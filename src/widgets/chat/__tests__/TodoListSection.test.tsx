import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

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

  it('copies todo list section as Markdown and JSON to clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<TodoListSection todos={TODOS} />);

    fireEvent.click(screen.getByTestId('todo-list-section-copy-md-btn'));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(expect.stringContaining('# 会话任务清单'));
    });

    fireEvent.click(screen.getByTestId('todo-list-section-copy-json-btn'));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(expect.stringContaining('"调研方案"'));
    });
  });
});
