import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../../entities/scheduled/taskStore', () => {
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

import { I18nProvider } from '../../../../shared/lib/i18n';
import { CronJobSection } from '../CronJobSection';

const noop = () => {};

describe('CronJobSection', () => {
  it('renders the section title and empty hint when no tasks', () => {
    render(
      <MemoryRouter>
        <I18nProvider>
          <CronJobSection collapsed={false} onToggleCollapsed={noop} />
        </I18nProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId('cron-task-list')).toBeTruthy();
  });

  it('renders a link to the /scheduled page', () => {
    render(
      <MemoryRouter>
        <I18nProvider>
          <CronJobSection collapsed={false} onToggleCollapsed={noop} />
        </I18nProvider>
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: /scheduled\.create|新建任务|New Task/i })).toBeTruthy();
  });
});
