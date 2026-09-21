import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useTodoStore } from '../../../entities/todo/todoStore';
import type { Todo } from '../../../shared/api/types';
import { TodoItem } from '../TodoItem';

vi.mock('../../../entities/todo/todoStore', () => ({
  useTodoStore: vi.fn((selector) =>
    selector({
      complete: vi.fn().mockResolvedValue(undefined),
      cancel: vi.fn().mockResolvedValue(undefined),
      delete: vi.fn().mockResolvedValue(undefined),
    }),
  ),
}));

function fixture(overrides: Partial<Todo> = {}): Todo {
  return {
    id: 1,
    title: 'Test',
    status: 'pending',
    priority: 'medium',
    is_recurring: false,
    created_at: '2026-09-21T00:00:00',
    updated_at: '2026-09-21T00:00:00',
    ...overrides,
  };
}

describe('TodoItem', () => {
  it('renders the title', () => {
    render(<TodoItem todo={fixture({ title: 'Buy milk' })} />);
    expect(screen.getByText('Buy milk')).toBeDefined();
  });

  it('shows the recurring icon only when is_recurring is true', () => {
    const { rerender } = render(<TodoItem todo={fixture({ is_recurring: false })} />);
    expect(screen.queryByTitle('Recurring')).toBeNull();

    rerender(<TodoItem todo={fixture({ is_recurring: true })} />);
    expect(screen.getByTitle('Recurring')).toBeDefined();
  });

  it('shows the due date when due_at is set', () => {
    render(<TodoItem todo={fixture({ due_at: '2026-12-01T00:00:00' })} />);
    expect(screen.getByText(/Due/)).toBeDefined();
  });

  it('invokes complete() when the complete button is clicked', async () => {
    const completeMock = vi.fn().mockResolvedValue(undefined);
    (useTodoStore as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (selector: (s: { complete: typeof completeMock }) => unknown) =>
        selector({ complete: completeMock }),
    );
    render(<TodoItem todo={fixture()} />);
    await screen.getByRole('button', { name: 'Mark complete' }).click();
    expect(completeMock).toHaveBeenCalledWith(1);
  });

  it('invokes delete() when the delete button is clicked', async () => {
    const deleteMock = vi.fn().mockResolvedValue(undefined);
    (useTodoStore as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (selector: (s: { delete: typeof deleteMock; complete: () => unknown }) => unknown) =>
        selector({ delete: deleteMock, complete: vi.fn() }),
    );
    render(<TodoItem todo={fixture()} />);
    await screen.getByRole('button', { name: 'Delete' }).click();
    expect(deleteMock).toHaveBeenCalledWith(1);
  });
});