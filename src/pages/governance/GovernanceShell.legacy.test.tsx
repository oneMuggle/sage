// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ProjectSummary } from '../../shared/api';
import { I18nProvider } from '../../shared/lib/i18n';

/* ── Mock API ─────────────────────────────────────────────────────── */

const mockList = vi.fn();
const mockUpdate = vi.fn();
const mockScaffold = vi.fn();
const mockUpdateAllowedPaths = vi.fn();
const mockListMilestones = vi.fn();
const mockGetProjectProfile = vi.fn();
const mockCreateProjectProfile = vi.fn();
const mockDeleteProjectProfile = vi.fn();
const mockOpen = vi.fn();

vi.mock('../../shared/api', () => ({
  projectApi: {
    list: (...args: unknown[]) => mockList(...args),
    update: (...args: unknown[]) => mockUpdate(...args),
    scaffold: (...args: unknown[]) => mockScaffold(...args),
    updateAllowedPaths: (...args: unknown[]) => mockUpdateAllowedPaths(...args),
    listMilestones: (...args: unknown[]) => mockListMilestones(...args),
    open: (...args: unknown[]) => mockOpen(...args),
  },
  memoryApi: {
    getProjectProfile: (...args: unknown[]) => mockGetProjectProfile(...args),
    createProjectProfile: (...args: unknown[]) => mockCreateProjectProfile(...args),
    deleteProjectProfile: (...args: unknown[]) => mockDeleteProjectProfile(...args),
  },
}));

/* ── Mock heavy child components ─────────────────────────────────── */

vi.mock('../../features/project-type', () => ({
  MilestoneManager: () => <div data-testid="milestone-manager-stub" />,
  PolymorphicArchetypeCards: () => <div data-testid="archetype-cards-stub" />,
  ProjectOverviewWidgets: () => <div data-testid="overview-widgets-stub" />,
  ProjectBootstrapPanel: () => <div data-testid="bootstrap-panel-stub" />,
  MilestoneProgressWidget: () => <div data-testid="milestone-progress-stub" />,
  GitStatusWidget: () => <div data-testid="git-widget-stub" />,
  WikiGenerationPanel: () => <div data-testid="wiki-panel-stub" />,
  TaskDecomposeDialog: () => <div data-testid="task-decompose-stub" />,
  ProjectTypeBadge: ({ type }: { type: string }) => <span data-testid="type-badge">{type}</span>,
  ReferenceManager: () => <div data-testid="reference-manager-stub" />,
}));

vi.mock('../../features/project-type/StudioMaterialsAndProfilePanels', () => ({
  StudioCharterTabPanel: () => <div data-testid="charter-panel-stub" />,
  StudioMaterialsTabPanel: () => <div data-testid="materials-panel-stub" />,
  StudioProfileTabPanel: () => <div data-testid="profile-panel-stub" />,
  StudioAllowedPathsTabPanel: () => <div data-testid="allowed-paths-stub" />,
}));

vi.mock('../../features/rules/RulesPanel', () => ({
  RulesPanel: ({ projectId }: { projectId: string }) => (
    <div data-testid="rules-panel-stub">{projectId}</div>
  ),
}));

vi.mock('../../features/playbook/PlaybookCard', () => ({
  PlaybookCard: () => <div data-testid="playbook-card-stub" />,
}));

vi.mock('../../features/project-type/archetypeBlueprints', () => ({
  ARCHETYPE_ORDER: ['coding', 'business', 'research', 'personal'],
  ARCHETYPE_BLUEPRINTS: {
    coding: {
      label: '全栈工程',
      stages: [
        { id: 'initiation', label: '启动' },
        { id: 'execution', label: '执行' },
      ],
    },
    business: { label: '商务合同', stages: [{ id: 'initiation', label: '立卷归集' }] },
    research: { label: '学术研究', stages: [{ id: 'initiation', label: '选题' }] },
    personal: { label: '个人知识', stages: [{ id: 'initiation', label: '建卡' }] },
  },
  getArchetypeBlueprint: (type: string) => {
    const map: Record<string, { label: string; stages: Array<{ id: string; label: string }> }> = {
      coding: {
        label: '全栈工程',
        stages: [
          { id: 'initiation', label: '启动' },
          { id: 'execution', label: '执行' },
        ],
      },
      business: { label: '商务合同', stages: [{ id: 'initiation', label: '立卷归集' }] },
      research: { label: '学术研究', stages: [{ id: 'initiation', label: '选题' }] },
      personal: { label: '个人知识', stages: [{ id: 'initiation', label: '建卡' }] },
    };
    return map[type] ?? map.coding;
  },
}));

/* ── Import SUT after mocks ──────────────────────────────────────── */

import { GovernanceShell } from './GovernanceShell';
import {
  formatProjectGovernanceAuditJson,
  formatProjectGovernanceAuditSnapshot,
} from './governanceAudit';

/* ── Fixtures ─────────────────────────────────────────────────────── */

const testProject: ProjectSummary = {
  id: 'proj-1',
  path: '/home/user/project',
  name: 'my-project',
  createdAt: 1,
  lastOpenedAt: 10,
  allowedPaths: ['/etc/shared'],
  sessionCount: 3,
  lastSessionId: 's1',
  description: 'A test project',
  instructions: 'Test instructions',
  projectType: 'coding',
  projectStage: 'initiation',
};

/* ── Helpers ──────────────────────────────────────────────────────── */

function renderAt(projectId: string, search = '') {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[`/projects/governance/${projectId}${search}`]}>
        <Routes>
          <Route path="/projects/governance/:projectId" element={<GovernanceShell />} />
        </Routes>
      </MemoryRouter>
    </I18nProvider>,
  );
}

/* ── Tests ────────────────────────────────────────────────────────── */

describe('GovernanceShell (legacy)', () => {
  beforeEach(() => {
    [
      mockList,
      mockUpdate,
      mockScaffold,
      mockUpdateAllowedPaths,
      mockListMilestones,
      mockGetProjectProfile,
      mockCreateProjectProfile,
      mockDeleteProjectProfile,
      mockOpen,
    ].forEach((m) => m.mockReset());
    mockList.mockResolvedValue([testProject]);
    mockListMilestones.mockResolvedValue([]);
    mockGetProjectProfile.mockResolvedValue({ items: [] });
  });

  it('shows loading state when project not found', async () => {
    mockList.mockResolvedValue([]);
    renderAt('nonexistent');
    expect(screen.getByTestId('governance-loading')).toBeInTheDocument();
    expect(screen.getByText('项目不存在或加载失败')).toBeInTheDocument();
  });

  it('renders the governance page with project name and type', async () => {
    renderAt('proj-1');
    await waitFor(() => {
      expect(screen.getByTestId('project-governance-page')).toBeInTheDocument();
    });
    expect(screen.getByText('my-project')).toBeInTheDocument();
    expect(screen.getByTestId('type-badge')).toHaveTextContent('coding');
    expect(screen.getByText('/home/user/project')).toBeInTheDocument();
  });

  it('renders 5 governance tabs', async () => {
    renderAt('proj-1');
    await waitFor(() => {
      expect(screen.getByTestId('project-governance-page')).toBeInTheDocument();
    });
    expect(screen.getByTestId('governance-tab-overview')).toBeInTheDocument();
    expect(screen.getByTestId('governance-tab-rules')).toBeInTheDocument();
    expect(screen.getByTestId('governance-tab-knowledge')).toBeInTheDocument();
    expect(screen.getByTestId('governance-tab-files')).toBeInTheDocument();
    expect(screen.getByTestId('governance-tab-settings')).toBeInTheDocument();
  });

  it('opens the file references manager from its tab', async () => {
    renderAt('proj-1');
    await waitFor(() => {
      expect(screen.getByTestId('project-governance-page')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('governance-tab-files'));
    expect(screen.getByTestId('reference-manager-stub')).toBeInTheDocument();
  });

  it('defaults to overview tab showing the project home and domain cards', async () => {
    renderAt('proj-1');
    await waitFor(() => {
      expect(screen.getByTestId('project-governance-page')).toBeInTheDocument();
    });
    expect(screen.getByTestId('project-home-summary')).toBeInTheDocument();
    expect(screen.getByTestId('project-current-stage-section')).toBeInTheDocument();
    expect(screen.getByTestId('archetype-cards-stub')).toBeInTheDocument();
    expect(screen.getByTestId('playbook-card-stub')).toBeInTheDocument();
    // Heavy advanced widgets are no longer on the overview tab.
    expect(screen.queryByTestId('overview-widgets-stub')).not.toBeInTheDocument();
  });

  it('moves the initialization wizard and advanced widgets into settings', async () => {
    renderAt('proj-1');
    await waitFor(() => {
      expect(screen.getByTestId('project-governance-page')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('governance-tab-settings'));
    expect(screen.getByTestId('bootstrap-panel-stub')).toBeInTheDocument();
    expect(screen.getByTestId('overview-widgets-stub')).toBeInTheDocument();
  });

  it('continues initialization from the home CTA when incomplete', async () => {
    renderAt('proj-1');
    await waitFor(() => {
      expect(screen.getByTestId('project-home-summary')).toBeInTheDocument();
    });
    expect(screen.getByTestId('project-home-cta')).toHaveTextContent('继续初始化');
    fireEvent.click(screen.getByTestId('project-home-cta'));
    expect(screen.getByTestId('bootstrap-panel-stub')).toBeInTheDocument();
  });

  it('starts a session from the home CTA when initialization is complete', async () => {
    mockList.mockResolvedValue([
      {
        ...testProject,
        bootstrapState: {
          applied: ['metadata.description', 'sage_md', 'rule', 'milestones', 'git_init'],
          appliedAt: 1,
        },
      },
    ]);
    mockOpen.mockResolvedValue({
      project: testProject,
      session: { id: 'session-1' },
      created: true,
    });
    renderAt('proj-1');
    await waitFor(() => {
      expect(screen.getByTestId('project-home-cta')).toHaveTextContent('开始会话');
    });
    fireEvent.click(screen.getByTestId('project-home-cta'));
    await waitFor(() => expect(mockOpen).toHaveBeenCalledWith('proj-1'));
  });

  it('keeps the milestone manager available in overview', async () => {
    renderAt('proj-1');
    await waitFor(() => {
      expect(screen.getByTestId('project-governance-page')).toBeInTheDocument();
    });

    expect(screen.getByTestId('milestone-manager-stub')).toBeInTheDocument();
  });

  it('moves the legacy knowledge=rules deep link to the rules tab', async () => {
    renderAt('proj-1', '?tab=knowledge&knowledge=rules');
    await waitFor(() => {
      expect(screen.getByTestId('project-governance-page')).toBeInTheDocument();
    });
    expect(screen.getByTestId('rules-panel-stub')).toHaveTextContent('proj-1');
  });

  it('drops the rules sub-tab from the knowledge section', async () => {
    renderAt('proj-1');
    await waitFor(() => {
      expect(screen.getByTestId('project-governance-page')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('governance-tab-knowledge'));
    await waitFor(() => {
      expect(screen.getByTestId('materials-panel-stub')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('governance-knowledge-rules')).toBeNull();
  });

  it('shows allowed paths under settings', async () => {
    renderAt('proj-1');
    await waitFor(() => {
      expect(screen.getByTestId('project-governance-page')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('governance-tab-settings'));
    await waitFor(() => {
      expect(screen.getByTestId('allowed-paths-stub')).toBeInTheDocument();
    });
  });

  it('type selector calls projectApi.update on change', async () => {
    mockUpdate.mockResolvedValue({ ...testProject, projectType: 'business' });
    renderAt('proj-1');
    await waitFor(() => {
      expect(screen.getByTestId('project-governance-page')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('governance-tab-settings'));
    const typeSelect = screen.getByLabelText('切换项目形态');
    fireEvent.change(typeSelect, { target: { value: 'business' } });

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalledWith(
        'proj-1',
        expect.objectContaining({
          project_type: 'business',
        }),
      );
    });
  });

  it('back button navigates to /projects', async () => {
    renderAt('proj-1');
    await waitFor(() => {
      expect(screen.getByTestId('project-governance-page')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('返回工作台'));
    await waitFor(() => {
      expect(screen.queryByTestId('project-governance-page')).not.toBeInTheDocument();
    });
  });

  it('formats audit snapshot and JSON and supports copy controls (Phase P100)', async () => {
    expect(
      formatProjectGovernanceAuditSnapshot({
        projectId: 'proj-1',
        projectType: 'coding',
        activeTab: 'rules',
        milestonesCount: 3,
        profileCount: 2,
        allowedPathsCount: 1,
        scaffolding: false,
      }),
    ).toBe(
      'projectGovernance|id=proj-1|type=coding|tab=rules|milestones=3|profile=2|paths=1|scaffolding=0',
    );
    expect(formatProjectGovernanceAuditSnapshot({})).toBe(
      'projectGovernance|id=none|type=business|tab=overview|milestones=0|profile=0|paths=0|scaffolding=0',
    );
    expect(
      JSON.parse(
        formatProjectGovernanceAuditJson({
          projectId: 'proj-1',
          projectType: 'coding',
          activeTab: 'overview',
          milestonesCount: 1,
          profileCount: 4,
          allowedPathsCount: 2,
          scaffolding: true,
        }),
      ),
    ).toEqual({
      projectId: 'proj-1',
      projectType: 'coding',
      activeTab: 'overview',
      milestonesCount: 1,
      profileCount: 4,
      allowedPathsCount: 2,
      scaffolding: true,
    });

    renderAt('proj-1');
    await waitFor(() => {
      expect(screen.getByTestId('project-governance-page')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('governance-tab-settings'));
    const snapBtn = screen.getByTestId('project-governance-copy-snapshot');
    const jsonBtn = screen.getByTestId('project-governance-copy-json');
    fireEvent.click(snapBtn);
    expect(snapBtn).toHaveTextContent('已复制快照');
    fireEvent.click(jsonBtn);
    expect(jsonBtn).toHaveTextContent('已复制JSON');
  });
});
