import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../../entities/scheduled/taskStore', () => {
  const state = {
    tasks: [],
    loading: false,
    error: null,
    load: vi.fn(),
    create: vi.fn().mockResolvedValue({}),
    update: vi.fn().mockResolvedValue({}),
    delete: vi.fn(),
    runNow: vi.fn(),
  };
  const hook = (sel?: (s: unknown) => unknown) => (sel ? sel(state) : state);
  return {
    useScheduledTaskStore: Object.assign(hook, { getState: () => state, setState: vi.fn() }),
  };
});

import { useScheduledTaskStore } from '../../../entities/scheduled/taskStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import { CreateTaskModal } from '../CreateTaskModal';

function renderModal(props: Partial<React.ComponentProps<typeof CreateTaskModal>> = {}) {
  return render(
    <I18nProvider>
      <CreateTaskModal open={true} onClose={vi.fn()} sessionId="s-1" {...props} />
    </I18nProvider>,
  );
}

describe('CreateTaskModal', () => {
  it('submit disabled until name and cron are filled', () => {
    renderModal();
    const submit = screen
      .getAllByRole('button')
      .find((b) => b.getAttribute('type') === 'submit') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
  });

  it('clicking cancel calls onClose', () => {
    const onClose = vi.fn();
    renderModal({ onClose });
    fireEvent.click(screen.getByText(/common\.cancel|取消|Cancel/i));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('filling name + cron enables submit, submit calls create() and onClose', async () => {
    const onClose = vi.fn();
    renderModal({ onClose });

    const nameInput = screen.getByPlaceholderText(/scheduled\.field\.name|Task name|任务名称/i);
    fireEvent.change(nameInput, { target: { value: 'My task' } });

    const contentArea =
      screen.getByRole('textbox', {
        name: /scheduled\.field\.content|Message content|发送内容/i,
      }) || document.querySelector('textarea');
    fireEvent.change(contentArea!, { target: { value: 'hello world' } });

    fireEvent.click(screen.getByTestId('cron-preset-hourly'));

    await waitFor(() => {
      const submit = screen
        .getAllByRole('button')
        .find((b) => b.getAttribute('type') === 'submit') as HTMLButtonElement;
      expect(submit.disabled).toBe(false);
    });

    const submit = screen
      .getAllByRole('button')
      .find((b) => b.getAttribute('type') === 'submit') as HTMLButtonElement;
    fireEvent.click(submit);

    await waitFor(() => {
      const state = useScheduledTaskStore.getState();
      expect(state.create).toHaveBeenCalledTimes(1);
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  it('edit mode prefills values from existing task and calls update()', async () => {
    const onClose = vi.fn();
    const existing = {
      id: 'task-1',
      name: 'Old name',
      type: 'recurring' as const,
      schedule: { kind: 'recurring' as const, cron: '0 8 * * *' },
      session_id: 's-1',
      content: 'hi',
      enabled: true,
      created_at: 0,
    };

    renderModal({ onClose, task: existing });

    const nameInput = screen.getByPlaceholderText(
      /scheduled\.field\.name|Task name|任务名称/i,
    ) as HTMLInputElement;
    expect(nameInput.value).toBe('Old name');

    fireEvent.change(nameInput, { target: { value: 'Renamed' } });

    const submit = screen
      .getAllByRole('button')
      .find((b) => b.getAttribute('type') === 'submit') as HTMLButtonElement;
    fireEvent.click(submit);

    await waitFor(() => {
      const state = useScheduledTaskStore.getState();
      expect(state.update).toHaveBeenCalledTimes(1);
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  it('shows server error inline when create throws', async () => {
    // Override the create mock on the live store before render
    const liveState = useScheduledTaskStore.getState() as unknown as {
      create: ReturnType<typeof vi.fn>;
    };
    liveState.create = vi.fn().mockRejectedValue(new Error('cron invalid'));

    renderModal();

    fireEvent.change(screen.getByPlaceholderText(/scheduled\.field\.name|Task name|任务名称/i), {
      target: { value: 'X' },
    });
    const contentArea = document.querySelector('textarea') as HTMLTextAreaElement;
    fireEvent.change(contentArea, { target: { value: 'X' } });
    fireEvent.click(screen.getByTestId('cron-preset-hourly'));

    const submit = screen
      .getAllByRole('button')
      .find((b) => b.getAttribute('type') === 'submit') as HTMLButtonElement;
    fireEvent.click(submit);

    await waitFor(() => {
      expect(screen.getByText('cron invalid')).toBeTruthy();
    });
  });
});
