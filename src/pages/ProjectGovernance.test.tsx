// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ProjectSummary } from '../shared/api';
import { I18nProvider } from '../shared/lib/i18n';

/* ── Mock API ─────────────────────────────────────────────────────── */

const mockList = vi.fn();
const mockUpdate = vi.fn();
const mockScaffold = vi.fn();
const mockUpdateAllowedPaths = vi.fn();
const mockListMilestones = vi.fn();
const mockGetProjectProfile = vi.fn();
const mockCreateProjectProfile = vi.fn();
const mockDeleteProjectProfile = vi.fn();

vi.mock('../shared/api', () => ({
  projectApi: {
    list: (...args: unknown[]) => mockList(...args),
    update: (...args: unknown[]) => mockUpdate(...args),
    scaffold: (...args: unknown[]) => mockScaffold(...args),
    updateAllowedPaths: (...args: unknown[]) => mockUpdateAllowedPaths(...args),
    listMilestones: (...args: unknown[]) => mockListMilestones(...args),
  },
  memoryApi: {
    getProjectProfile: (...args: unknown[]) => mockGetProjectProfile(...args),
    createProjectProfile: (...args: unknown[]) => mockCreateProjectProfile(...args),
    deleteProjectProfile: (...args: unknown[]) => mockDeleteProjectProfile(...args),
  },
}));

/* ── Mock heavy child components ─────────────────────────────────── */

vi.mock('../features/project-type', () => ({
  MilestoneManager: () => <div data-testid="milestone-manager-stub" />,
  PolymorphicArchetypeCards: () => <div data-testid="archetype-cards-stub" />,
  ProjectOverviewWidgets: () => <div data-testid="overview-widgets-stub" />,
  ProjectBootstrapPanel: () => <div data-testid="bootstrap-panel-stub" />,
  ProjectTypeBadge: ({ type }: { type: string }) => <span data-testid="type-badge">{type}</span>,
  GovernanceRulesPanel: () => <div data-testid="rules-panel-stub" />,
}));

vi.mock('../features/project-type/StudioMaterialsAndProfilePanels', () => ({
  StudioCharterTabPanel: () => <div data-testid="charter-panel-stub" />,
  StudioMaterialsTabPanel: () => <div data-testid="materials-panel-stub" />,
  StudioProfileTabPanel: () => <div data-testid="profile-panel-stub" />,
}));

vi.mock('../features/playbook/PlaybookCard', () => ({
  PlaybookCard: () => <div data-testid="playbook-card-stub" />,
}));

vi.mock('../features/project-type/archetypeBlueprints', () => ({
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

import {
  ProjectGovernance,
  formatProjectGovernanceAuditJson,
  formatProjectGovernanceAuditSnapshot,
} from './ProjectGovernance';

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

function renderAt(projectId: string) {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[`/projects/governance/${projectId}`]}>
        <Routes>
          <Route path="/projects/governance/:projectId" element={<ProjectGovernance />} />
        </Routes>
      </MemoryRouter>
    </I18nProvider>,
  );
}

/* ── Tests ────────────────────────────────────────────────────────── */

describe('ProjectGovernance', () => {
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

  it('renders 3 governance tabs', async () => {
    renderAt('proj-1');
    await waitFor(() => {
      expect(screen.getByTestId('project-governance-page')).toBeInTheDocument();
    });
    expect(screen.getByTestId('governance-tab-overview')).toBeInTheDocument();
    expect(screen.getByTestId('governance-tab-knowledge')).toBeInTheDocument();
    expect(screen.getByTestId('governance-tab-settings')).toBeInTheDocument();
  });

  it('defaults to overview tab showing archetype cards', async () => {
    renderAt('proj-1');
    await waitFor(() => {
      expect(screen.getByTestId('project-governance-page')).toBeInTheDocument();
    });
    expect(screen.getByTestId('archetype-cards-stub')).toBeInTheDocument();
    expect(screen.getByTestId('overview-widgets-stub')).toBeInTheDocument();
  });

  it('switches to rules sub-tab under project knowledge', async () => {
    renderAt('proj-1');
    await waitFor(() => {
      expect(screen.getByTestId('project-governance-page')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('governance-tab-knowledge'));
    fireEvent.click(screen.getByTestId('governance-knowledge-rules'));
    await waitFor(() => {
      expect(screen.getByTestId('rules-panel-stub')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('archetype-cards-stub')).not.toBeInTheDocument();
  });

  it('keeps the milestone manager available in overview', async () => {
    renderAt('proj-1');
    await waitFor(() => {
      expect(screen.getByTestId('project-governance-page')).toBeInTheDocument();
    });

    expect(screen.getByTestId('milestone-manager-stub')).toBeInTheDocument();
  });

  it('rules sub-tab label shows allowed paths count', async () => {
    renderAt('proj-1');
    await waitFor(() => {
      expect(screen.getByTestId('project-governance-page')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('governance-tab-knowledge'));
    expect(screen.getByTestId('governance-knowledge-rules')).toHaveTextContent('规则与约束 (1)');
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
