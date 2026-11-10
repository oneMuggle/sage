import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

const { list, setStatus } = vi.hoisted(() => ({ list: vi.fn(), setStatus: vi.fn() }));

vi.mock('../../shared/lib/i18n', () => ({
  useI18n: () => ({ locale: 'en', t: (key: string) => key }),
}));
vi.mock('../../widgets/sidebar/sections/WorkbenchProjectList', () => ({
  WorkbenchProjectList: () => <div data-testid="overview-list" />,
}));
vi.mock('../../shared/api', async () => {
  const actual = await vi.importActual<typeof import('../../shared/api')>('../../shared/api');
  return { ...actual, projectApi: { ...actual.projectApi, list, setProjectStatus: setStatus } };
});

import { ProjectsOverview } from '../ProjectsOverview';

const ROWS = [
  {
    id: 'p-1',
    name: 'Sage',
    path: '/w/sage',
    projectType: 'coding',
    lastOpenedAt: 30,
    createdAt: 1,
    sessionCount: 2,
    lastSessionId: null,
    allowedPaths: [],
    status: 'active',
  },
  {
    id: 'p-2',
    name: 'Paper',
    path: '/w/paper',
    projectType: 'research',
    lastOpenedAt: 10,
    createdAt: 1,
    sessionCount: 0,
    lastSessionId: null,
    allowedPaths: [],
    status: 'archived',
  },
];

function renderPage() {
  return render(
    <MemoryRouter>
      <ProjectsOverview />
    </MemoryRouter>,
  );
}

describe('ProjectsOverview', () => {
  it('lists active projects by default and filters by query', async () => {
    list.mockResolvedValue(ROWS);
    renderPage();
    await waitFor(() => expect(screen.getByTestId('projects-overview-rows')).toBeInTheDocument());
    expect(screen.getByText('Sage')).toBeInTheDocument();
    expect(screen.queryByText('Paper')).not.toBeInTheDocument();

    fireEvent.change(screen.getByTestId('projects-overview-search'), { target: { value: 'sag' } });
    expect(screen.getByText('Sage')).toBeInTheDocument();
  });

  it('switches to archived filter', async () => {
    list.mockResolvedValue(ROWS);
    renderPage();
    await waitFor(() => expect(screen.getByText('Sage')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('projects-overview-status-archived'));
    expect(screen.getByText('Paper')).toBeInTheDocument();
    expect(screen.queryByText('Sage')).not.toBeInTheDocument();
  });

  it('archives a selected project', async () => {
    list.mockResolvedValue(ROWS);
    setStatus.mockResolvedValue({ ...ROWS[0], status: 'archived' });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId('projects-overview-row-p-1')).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId('projects-overview-select-p-1'));
    fireEvent.click(screen.getByTestId('projects-overview-archive'));
    await waitFor(() => expect(setStatus).toHaveBeenCalledWith('p-1', 'archived'));
  });

  it('加载失败时展示错误横幅而非静默空态', async () => {
    list.mockRejectedValue(new Error('后端服务尚未就绪,请稍候或重启 Sage'));
    renderPage();
    await waitFor(() => expect(screen.getByTestId('projects-overview-error')).toBeInTheDocument());
    expect(screen.getByText(/加载项目列表失败/)).toBeInTheDocument();
  });

  it('点击重试后重新拉取并清除错误横幅', async () => {
    list.mockRejectedValueOnce(new Error('后端服务尚未就绪,请稍候或重启 Sage'));
    renderPage();
    await waitFor(() => expect(screen.getByTestId('projects-overview-error')).toBeInTheDocument());

    list.mockResolvedValueOnce(ROWS);
    fireEvent.click(screen.getByRole('button', { name: '重试' }));

    await waitFor(() =>
      expect(screen.queryByTestId('projects-overview-error')).not.toBeInTheDocument(),
    );
    expect(screen.getByText('Sage')).toBeInTheDocument();
  });
});
