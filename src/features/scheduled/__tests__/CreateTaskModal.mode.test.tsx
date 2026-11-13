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

function submitButton(): HTMLButtonElement {
  return screen
    .getAllByRole('button')
    .find((b) => b.getAttribute('type') === 'submit') as HTMLButtonElement;
}

async function fillRequired() {
  fireEvent.change(screen.getByPlaceholderText(/scheduled\.field\.name|Task name|任务名称/i), {
    target: { value: 'Mode task' },
  });
  const contentArea =
    (screen.queryByRole('textbox', {
      name: /scheduled\.field\.content|Message content|发送内容/i,
    }) as HTMLTextAreaElement | null) ??
    (document.querySelector('textarea') as HTMLTextAreaElement);
  fireEvent.change(contentArea, { target: { value: 'hello mode' } });
  fireEvent.click(screen.getByTestId('cron-preset-hourly'));
  await waitFor(() => expect(submitButton().disabled).toBe(false));
}

describe('CreateTaskModal execution mode', () => {
  it('defaults to deliver mode', () => {
    renderModal();
    const deliver = screen.getByRole('radio', {
      name: /scheduled\.mode\.deliver|Deliver directly|直接发送/i,
    }) as HTMLInputElement;
    const execute = screen.getByRole('radio', {
      name: /scheduled\.mode\.execute|Auto-execute|自动执行/i,
    }) as HTMLInputElement;
    expect(deliver.checked).toBe(true);
    expect(execute.checked).toBe(false);
  });

  it('submits mode="deliver" by default', async () => {
    const liveState = useScheduledTaskStore.getState() as unknown as {
      create: ReturnType<typeof vi.fn>;
    };
    liveState.create = vi.fn().mockResolvedValue({});

    renderModal();
    await fillRequired();
    fireEvent.click(submitButton());

    await waitFor(() => {
      expect(liveState.create).toHaveBeenCalledWith(expect.objectContaining({ mode: 'deliver' }));
    });
  });

  it('submits mode="execute" after selecting it', async () => {
    const liveState = useScheduledTaskStore.getState() as unknown as {
      create: ReturnType<typeof vi.fn>;
    };
    liveState.create = vi.fn().mockResolvedValue({});

    renderModal();
    await fillRequired();
    fireEvent.click(
      screen.getByRole('radio', {
        name: /scheduled\.mode\.execute|Auto-execute|自动执行/i,
      }),
    );
    fireEvent.click(submitButton());

    await waitFor(() => {
      expect(liveState.create).toHaveBeenCalledWith(expect.objectContaining({ mode: 'execute' }));
    });
  });

  it('edit mode prefills the stored mode', () => {
    const existing = {
      id: 'task-1',
      name: 'Old',
      type: 'recurring' as const,
      schedule: { kind: 'recurring' as const, cron: '0 8 * * *' },
      session_id: 's-1',
      content: 'hi',
      enabled: true,
      created_at: 0,
      mode: 'execute' as const,
    };
    renderModal({ task: existing });
    const execute = screen.getByRole('radio', {
      name: /scheduled\.mode\.execute|Auto-execute|自动执行/i,
    }) as HTMLInputElement;
    expect(execute.checked).toBe(true);
  });

  it('edit mode submits updated mode', async () => {
    const liveState = useScheduledTaskStore.getState() as unknown as {
      update: ReturnType<typeof vi.fn>;
    };
    liveState.update = vi.fn().mockResolvedValue({});

    const existing = {
      id: 'task-1',
      name: 'Old',
      type: 'recurring' as const,
      schedule: { kind: 'recurring' as const, cron: '0 8 * * *' },
      session_id: 's-1',
      content: 'hi',
      enabled: true,
      created_at: 0,
      mode: 'deliver' as const,
    };
    renderModal({ task: existing });
    fireEvent.click(
      screen.getByRole('radio', {
        name: /scheduled\.mode\.execute|Auto-execute|自动执行/i,
      }),
    );
    fireEvent.click(submitButton());

    await waitFor(() => {
      expect(liveState.update).toHaveBeenCalledWith(
        'task-1',
        expect.objectContaining({ mode: 'execute' }),
      );
    });
  });
});
