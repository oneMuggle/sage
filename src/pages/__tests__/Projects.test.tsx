import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { projectApi } from '../../shared/api';
import { Projects } from '../Projects';

vi.mock('../../shared/lib/i18n', () => ({ useI18n: () => ({ locale: 'en' }) }));
const { props } = vi.hoisted(() => ({ props: vi.fn() }));
vi.mock('../../widgets/sidebar/sections/WorkbenchProjectList', () => ({
  WorkbenchProjectList: (value: unknown) => {
    props(value);
    return <div data-testid="projects-existing-api-view" />;
  },
}));
vi.mock('../../shared/api', async () => {
  const actual = await vi.importActual<typeof import('../../shared/api')>('../../shared/api');
  return {
    ...actual,
    projectApi: {
      ...actual.projectApi,
      list: vi.fn().mockResolvedValue([
        {
          id: 'p-1',
          name: 'SageCore',
          path: '/workspace/sage',
          projectType: 'coding',
          projectStage: 'development',
          vcsMode: 'git',
          createdAt: 1,
          lastOpenedAt: 2,
          sessionCount: 4,
          lastSessionId: 's-1',
          allowedPaths: [],
        },
      ]),
    },
  };
});

describe('project workbench', () => {
  it('uses the existing project view with a spacious presentation and renders Phase P31 workbench toolbar', async () => {
    render(
      <MemoryRouter>
        <Projects />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('project-workbench')).toBeInTheDocument();
    expect(screen.getByTestId('project-workbench-toolbar')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId('workbench-project-count')).toHaveTextContent('已纳管项目：1 个');
    });
    expect(projectApi.list).toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('workbench-export-registry-md-btn'));
    expect(screen.getByTestId('workbench-export-registry-md-btn')).toHaveTextContent(
      /已复制台账|导出项目台账 MD/,
    );
    fireEvent.click(screen.getByTestId('workbench-copy-paths-btn'));
    fireEvent.click(screen.getByTestId('workbench-copy-archetype-stats-btn'));
    fireEvent.click(screen.getByTestId('workbench-refresh-registry-btn'));
    fireEvent.click(screen.getByTestId('workbench-save-registry-l4-btn'));
    expect(screen.getByTestId('workbench-save-registry-l4-btn')).toHaveTextContent('已存台账L4');
    fireEvent.click(screen.getByTestId('workbench-save-registry-l3-btn'));
    expect(screen.getByTestId('workbench-save-registry-l3-btn')).toHaveTextContent('已存台账L3');

    expect(props).toHaveBeenCalledWith(
      expect.objectContaining({ onOpenSession: expect.any(Function) }),
    );
    expect(screen.getByText(/folder binding still controls file access/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'New deliverable' }));

    fireEvent.click(screen.getByTestId('workbench-open-wizard-btn'));
    expect(await screen.findByText('创建多形态项目')).toBeInTheDocument();
  });
});
