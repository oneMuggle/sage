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
  it('renders three-section layout with quickstart, project list, and advanced area', async () => {
    render(
      <MemoryRouter>
        <Projects />
      </MemoryRouter>,
    );

    // Section 1: Quick start card
    expect(screen.getByTestId('workbench-quickstart')).toBeInTheDocument();
    expect(screen.getByTestId('workbench-cta-new-chat')).toBeInTheDocument();
    expect(screen.getByTestId('workbench-cta-add-project')).toBeInTheDocument();

    // Section 2: Project list with count (English locale mock → "1 project")
    await waitFor(() => {
      expect(screen.getByTestId('workbench-project-count')).toHaveTextContent('1 project');
    });
    expect(projectApi.list).toHaveBeenCalled();
    expect(screen.getByTestId('workbench-refresh-btn')).toBeInTheDocument();

    // Section 3: Advanced area (collapsed by default, toggle to open)
    const advancedToggle = screen.getByTestId('workbench-advanced-toggle');
    fireEvent.click(advancedToggle);
    expect(screen.getByTestId('workbench-copy-paths-btn')).toBeInTheDocument();
    expect(screen.getByTestId('workbench-export-registry-md-btn')).toBeInTheDocument();

    // Copy paths and export markdown still work
    fireEvent.click(screen.getByTestId('workbench-export-registry-md-btn'));
    fireEvent.click(screen.getByTestId('workbench-copy-paths-btn'));

    // WorkbenchProjectList receives onOpenSession prop
    expect(props).toHaveBeenCalledWith(
      expect.objectContaining({ onOpenSession: expect.any(Function) }),
    );

    // Opening wizard from quickstart card
    fireEvent.click(screen.getByTestId('workbench-cta-add-project'));
    expect(await screen.findByText('创建多形态项目')).toBeInTheDocument();
  });
});
