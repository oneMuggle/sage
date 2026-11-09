import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

const { setStatus } = vi.hoisted(() => ({ setStatus: vi.fn() }));

vi.mock('../../shared/lib/i18n', () => ({
  useI18n: () => ({ locale: 'en', t: (key: string) => key }),
}));
vi.mock('../../widgets/sidebar/sections/WorkbenchProjectList', () => ({
  WorkbenchProjectList: (props: {
    filters?: { q: string; status: string };
    selectable?: boolean;
    selectedIds?: string[];
    addSignal?: number;
    onToggleSelect?: (id: string) => void;
    onOpenSession?: (id: string) => void;
  }) => (
    <div data-testid="projects-list-mock">
      <span data-testid="filters-q">{props.filters?.q ?? ''}</span>
      <span data-testid="filters-status">{props.filters?.status ?? ''}</span>
      <span data-testid="selectable">{String(Boolean(props.selectable))}</span>
      <span data-testid="selected-count">{props.selectedIds?.length ?? 0}</span>
      <span data-testid="add-signal">{props.addSignal ?? 0}</span>
      <button data-testid="mock-toggle-p1" onClick={() => props.onToggleSelect?.('p-1')} />
    </div>
  ),
}));
vi.mock('../../shared/api', async () => {
  const actual = await vi.importActual<typeof import('../../shared/api')>('../../shared/api');
  return { ...actual, projectApi: { ...actual.projectApi, setProjectStatus: setStatus } };
});

import { ProjectsOverview } from '../ProjectsOverview';

function renderPage() {
  return render(
    <MemoryRouter>
      <ProjectsOverview />
    </MemoryRouter>,
  );
}

describe('ProjectsOverview', () => {
  it('renders the single project list with default active filter', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('projects-list-mock')).toBeInTheDocument());
    expect(screen.getByTestId('filters-status')).toHaveTextContent('active');
    expect(screen.getByTestId('filters-q')).toHaveTextContent('');
  });

  it('filters by query and switches status', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('projects-list-mock')).toBeInTheDocument());

    fireEvent.change(screen.getByTestId('projects-overview-search'), {
      target: { value: 'sag' },
    });
    expect(screen.getByTestId('filters-q')).toHaveTextContent('sag');

    fireEvent.click(screen.getByTestId('projects-overview-status-archived'));
    expect(screen.getByTestId('filters-status')).toHaveTextContent('archived');
  });

  it('enters batch mode and archives selected projects', async () => {
    setStatus.mockResolvedValue({});
    renderPage();
    await waitFor(() => expect(screen.getByTestId('projects-list-mock')).toBeInTheDocument());

    expect(screen.getByTestId('selectable')).toHaveTextContent('false');
    fireEvent.click(screen.getByTestId('projects-overview-select-mode'));
    expect(screen.getByTestId('selectable')).toHaveTextContent('true');

    fireEvent.click(screen.getByTestId('mock-toggle-p1'));
    expect(screen.getByTestId('selected-count')).toHaveTextContent('1');

    fireEvent.click(screen.getByTestId('projects-overview-archive'));
    await waitFor(() => expect(setStatus).toHaveBeenCalledWith('p-1', 'archived'));
  });

  it('opens the add dialog signal from the page header', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('projects-list-mock')).toBeInTheDocument());
    expect(screen.getByTestId('add-signal')).toHaveTextContent('0');
    fireEvent.click(screen.getByTestId('projects-overview-new'));
    expect(screen.getByTestId('add-signal')).toHaveTextContent('1');
  });
});
