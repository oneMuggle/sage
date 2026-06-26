import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../entities/scheduled/taskStore', () => {
  const state = {
    tasks: [],
    loading: false,
    error: null,
    load: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    runNow: vi.fn(),
  };
  const hook = (sel?: (s: unknown) => unknown) => (sel ? sel(state) : state);
  return {
    useScheduledTaskStore: Object.assign(hook, { getState: () => state }),
  };
});

import { I18nProvider } from '../../shared/lib/i18n';
import { ScheduledTasks } from '../ScheduledTasks';

describe('ScheduledTasks page', () => {
  it('renders title and Create button', () => {
    render(
      <MemoryRouter>
        <I18nProvider>
          <ScheduledTasks />
        </I18nProvider>
      </MemoryRouter>,
    );
    expect(screen.getAllByText(/定时任务|Scheduled/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/scheduled\.create|新建任务|New Task/i).length).toBeGreaterThan(0);
  });

  it('clicking Create opens the modal', () => {
    render(
      <MemoryRouter>
        <I18nProvider>
          <ScheduledTasks />
        </I18nProvider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getAllByText(/scheduled\.create|新建任务|New Task/i)[0]);
    expect(screen.getByRole('dialog')).toBeTruthy();
  });
});
