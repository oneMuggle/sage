import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Todo } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { TodoItem } from '../TodoItem';

const mocks = vi.hoisted(() => ({
  complete: vi.fn().mockResolvedValue(undefined),
  remove: vi.fn().mockResolvedValue(undefined),
  confirmDialog: vi.fn(),
}));

vi.mock('../../../entities/todo/todoStore', () => ({
  useTodoStore: vi.fn((selector) =>
    selector({
      complete: mocks.complete,
      cancel: vi.fn(),
      delete: mocks.remove,
    }),
  ),
}));

vi.mock('../../../shared/ui/ConfirmDialog/confirmService', () => ({
  confirmDialog: mocks.confirmDialog,
}));

const todo = (overrides: Partial<Todo> = {}): Todo => ({
  id: 3,
  title: 'Write report',
  status: 'pending',
  priority: 'medium',
  is_recurring: false,
  created_at: '2026-09-21T00:00:00',
  updated_at: '2026-09-21T00:00:00',
  ...overrides,
});

function renderItem() {
  return render(
    <I18nProvider defaultLocale="zh">
      <TodoItem todo={todo()} />
    </I18nProvider>,
  );
}

function openMenu() {
  fireEvent.contextMenu(screen.getByText('Write report'), { clientX: 4, clientY: 4 });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('TodoItem — context menu', () => {
  it('completes and confirms deletion through the store', async () => {
    mocks.confirmDialog.mockResolvedValueOnce(true);
    renderItem();

    openMenu();
    fireEvent.click(await screen.findByRole('menuitem', { name: '标记完成' }));
    expect(mocks.complete).toHaveBeenCalledWith(3);

    openMenu();
    fireEvent.click(await screen.findByRole('menuitem', { name: '删除待办…' }));
    await waitFor(() => expect(mocks.remove).toHaveBeenCalledWith(3));
  });
});
