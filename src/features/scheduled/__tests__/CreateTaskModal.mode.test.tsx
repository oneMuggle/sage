import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

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

beforeEach(() => {
  const state = useScheduledTaskStore.getState();
  (state.create as ReturnType<typeof vi.fn>).mockClear();
  (state.update as ReturnType<typeof vi.fn>).mockClear();
});

describe('CreateTaskModal — mode selector', () => {
  it('defaults to execute mode for new task', () => {
    renderModal();
    const execBtn = screen.getByTestId('mode-execute-button') as HTMLButtonElement;
    const deliverBtn = screen.getByTestId('mode-deliver-button') as HTMLButtonElement;
    expect(execBtn.className).toMatch(/bg-primary|border-primary/);
    expect(deliverBtn.className).not.toMatch(/bg-primary/);
  });

  it('inherits mode from editing task', () => {
    renderModal({
      task: {
        id: 'existing',
        name: 'old',
        type: 'recurring',
        schedule: { kind: 'recurring', cron: '0 8 * * *' },
        session_id: 's-1',
        content: 'hello',
        enabled: true,
        mode: 'deliver',
        created_at: Date.now(),
      },
    });
    const deliverBtn = screen.getByTestId('mode-deliver-button') as HTMLButtonElement;
    expect(deliverBtn.className).toMatch(/bg-primary|border-primary/);
  });

  it('switching mode and submitting passes mode to store.create', async () => {
    renderModal();
    fireEvent.change(screen.getByPlaceholderText(/scheduled\.field\.name|Task name|任务名称/i), {
      target: { value: 'Test task' },
    });
    const textarea = document.querySelector('textarea')!;
    fireEvent.change(textarea, { target: { value: 'do work' } });
    fireEvent.click(screen.getByTestId('cron-preset-hourly'));

    fireEvent.click(screen.getByTestId('mode-deliver-button'));

    const submit = screen
      .getAllByRole('button')
      .find((b) => b.getAttribute('type') === 'submit') as HTMLButtonElement;

    await waitFor(() => expect(submit.disabled).toBe(false));
    fireEvent.click(submit);

    await waitFor(() => {
      const state = useScheduledTaskStore.getState();
      expect(state.create).toHaveBeenCalledTimes(1);
      const payload = (state.create as ReturnType<typeof vi.fn>).mock.calls[0][0];
      expect(payload.mode).toBe('deliver');
    });
  });

  it('submitting without switching mode defaults to execute', async () => {
    renderModal();
    fireEvent.change(screen.getByPlaceholderText(/scheduled\.field\.name|Task name|任务名称/i), {
      target: { value: 'Test task' },
    });
    const textarea = document.querySelector('textarea')!;
    fireEvent.change(textarea, { target: { value: 'do work' } });
    fireEvent.click(screen.getByTestId('cron-preset-hourly'));

    const submit = screen
      .getAllByRole('button')
      .find((b) => b.getAttribute('type') === 'submit') as HTMLButtonElement;
    await waitFor(() => expect(submit.disabled).toBe(false));
    fireEvent.click(submit);

    await waitFor(() => {
      const state = useScheduledTaskStore.getState();
      expect(state.create).toHaveBeenCalledTimes(1);
      const payload = (state.create as ReturnType<typeof vi.fn>).mock.calls[0][0];
      expect(payload.mode).toBe('execute');
    });
  });
});
