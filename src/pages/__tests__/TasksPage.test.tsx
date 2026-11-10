import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../features/task-center/TaskCenterPanel', () => ({
  TaskCenterPanel: ({ variant }: { variant: string }) => <div data-testid="panel">{variant}</div>,
}));

import { I18nProvider } from '../../shared/lib/i18n';
import { TasksPage } from '../TasksPage';

describe('TasksPage', () => {
  beforeEach(() => vi.clearAllMocks());

  it('渲染标题、副标题与 full 模式面板', () => {
    render(
      <I18nProvider>
        <MemoryRouter>
          <TasksPage />
        </MemoryRouter>
      </I18nProvider>,
    );
    expect(screen.getByText('任务中心')).toBeTruthy();
    expect(screen.getByTestId('panel').textContent).toBe('full');
  });
});
