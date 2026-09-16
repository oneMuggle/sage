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

const auditTask = {
  id: 'audit-a',
  name: 'Task A',
  type: 'recurring' as const,
  schedule: { kind: 'recurring' as const, cron: '0 8 * * *' },
  session_id: 's-1',
  content: 'Content A',
  enabled: true,
  created_at: 0,
};
const formTree = (props: Partial<React.ComponentProps<typeof CreateTaskModal>>) => (
  <I18nProvider>
    <CreateTaskModal open onClose={vi.fn()} sessionId="s-1" {...props} />
  </I18nProvider>
);
const submitButton = () => document.querySelector('button[type="submit"]') as HTMLButtonElement;

describe('scheduled audit form contracts', () => {
  it('hydrates after closed mount and resets A to B to a new form', () => {
    const view = render(formTree({ open: false }));
    view.rerender(formTree({ task: auditTask }));
    expect(screen.getByDisplayValue('Task A')).toBeTruthy();
    view.rerender(
      formTree({ task: { ...auditTask, id: 'audit-b', name: 'Task B', content: 'Content B' } }),
    );
    expect(screen.getByDisplayValue('Task B')).toBeTruthy();
    expect(screen.queryByDisplayValue('Content A')).toBeNull();
    view.rerender(formTree({ task: undefined }));
    expect((document.querySelector('textarea') as HTMLTextAreaElement).value).toBe('');
  });

  it('submits edited content, schedule and actual target session', async () => {
    render(
      formTree({ task: auditTask, sessions: [{ id: 's-1' }, { id: 's-2', title: 'Second' }] }),
    );
    fireEvent.change(document.querySelector('textarea')!, {
      target: { value: 'New instructions' },
    });
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 's-2' } });
    fireEvent.click(screen.getByTestId('cron-preset-hourly'));
    fireEvent.click(submitButton());
    await waitFor(() =>
      expect(useScheduledTaskStore.getState().update).toHaveBeenCalledWith(
        'audit-a',
        expect.objectContaining({
          content: 'New instructions',
          session_id: 's-2',
          schedule: { kind: 'recurring', cron: '0 * * * *' },
        }),
      ),
    );
  });

  it('sends enabled=false on creation', async () => {
    const state = useScheduledTaskStore.getState();
    state.create = vi.fn().mockResolvedValue({});
    render(formTree({}));
    fireEvent.change(screen.getByPlaceholderText(/scheduled\.field\.name|Task name|任务名称/i), {
      target: { value: 'Paused' },
    });
    fireEvent.change(document.querySelector('textarea')!, { target: { value: 'hello' } });
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(submitButton());
    await waitFor(() =>
      expect(state.create).toHaveBeenCalledWith(
        expect.objectContaining({ enabled: false, session_id: 's-1' }),
      ),
    );
  });

  it('blocks submission without an existing target session', () => {
    render(formTree({ task: auditTask, sessions: [] }));
    expect(submitButton().disabled).toBe(true);
  });

  it('allows renaming a paused expired once task and preserves its timestamp', async () => {
    render(
      formTree({
        task: {
          ...auditTask,
          enabled: false,
          type: 'once',
          schedule: { kind: 'once', at: 1234567 },
        },
      }),
    );
    expect(submitButton().disabled).toBe(false);
    fireEvent.click(submitButton());
    await waitFor(() =>
      expect(useScheduledTaskStore.getState().update).toHaveBeenCalledWith(
        'audit-a',
        expect.objectContaining({ schedule: { kind: 'once', at: 1234567 }, enabled: false }),
      ),
    );
  });
});
