import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Todo } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { TodoRowEditor } from '../TodoRowEditor';

const mocks = vi.hoisted(() => ({
  confirmDialog: vi.fn(),
}));

vi.mock('../../../shared/ui/ConfirmDialog/confirmService', () => ({
  confirmDialog: mocks.confirmDialog,
}));

const todo = (overrides: Partial<Todo> = {}): Todo => ({
  id: 7,
  title: '买牛奶',
  status: 'pending',
  priority: 'medium',
  is_recurring: false,
  created_at: '2026-09-21T00:00:00',
  updated_at: '2026-09-21T00:00:00',
  ...overrides,
});

function renderRow(overrides: Partial<Parameters<typeof TodoRowEditor>[0]> = {}) {
  return render(
    <I18nProvider defaultLocale="zh">
      <ul>
        <TodoRowEditor
          todo={todo()}
          selected={false}
          onSelect={vi.fn()}
          onUpdate={vi.fn().mockResolvedValue(undefined)}
          onComplete={vi.fn().mockResolvedValue(undefined)}
          onCancel={vi.fn().mockResolvedValue(undefined)}
          onDelete={vi.fn().mockResolvedValue(undefined)}
          {...overrides}
        />
      </ul>
    </I18nProvider>,
  );
}

function openMenu() {
  fireEvent.contextMenu(screen.getByText('买牛奶'), { clientX: 4, clientY: 4 });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('TodoRowEditor — context menu', () => {
  it('exposes todo actions and completes through the existing handler', async () => {
    const onComplete = vi.fn().mockResolvedValue(undefined);
    renderRow({ onComplete });

    openMenu();
    expect(await screen.findByRole('menuitem', { name: '编辑标题' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '标记完成' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '取消待办' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '优先级' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '复制标题' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '删除待办…' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('menuitem', { name: '标记完成' }));
    await waitFor(() => expect(onComplete).toHaveBeenCalledWith(7));
  });

  it('enters inline title editing from the menu', async () => {
    renderRow();
    openMenu();
    fireEvent.click(await screen.findByRole('menuitem', { name: '编辑标题' }));
    expect(screen.getByTestId('todo-title-edit-input')).toBeInTheDocument();
  });

  it('confirms before deleting', async () => {
    const onDelete = vi.fn().mockResolvedValue(undefined);
    mocks.confirmDialog.mockResolvedValueOnce(true);
    renderRow({ onDelete });

    openMenu();
    fireEvent.click(await screen.findByRole('menuitem', { name: '删除待办…' }));

    await waitFor(() => expect(onDelete).toHaveBeenCalledWith(7));
    expect(mocks.confirmDialog.mock.calls[0][0]).toMatchObject({ danger: true });
  });

  it('hides editing actions for inactive todos', async () => {
    renderRow({ todo: todo({ status: 'completed' }) });
    fireEvent.contextMenu(screen.getByText('买牛奶'), { clientX: 4, clientY: 4 });

    await screen.findByRole('menuitem', { name: '复制标题' });
    expect(screen.queryByRole('menuitem', { name: '编辑标题' })).toBeNull();
    expect(screen.queryByRole('menuitem', { name: '标记完成' })).toBeNull();
  });
});
