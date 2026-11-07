import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { governance } = vi.hoisted(() => ({ governance: vi.fn() }));

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ locale: 'zh', setLocale: vi.fn(), t: (key: string) => key }),
}));
vi.mock('../useGovernanceProject', () => ({ useGovernanceProject: governance }));
vi.mock('../sections/OverviewSection', () => ({
  OverviewSection: ({ onChangeTab }: { onChangeTab: (tab: string) => void }) => (
    <div data-testid="section-overview">
      <button type="button" onClick={() => onChangeTab('settings')}>
        go-settings
      </button>
    </div>
  ),
}));
vi.mock('../sections/KnowledgeSection', () => ({
  KnowledgeSection: () => <div data-testid="section-knowledge" />,
}));
vi.mock('../sections/FilesSection', () => ({
  FilesSection: () => <div data-testid="section-files" />,
}));
vi.mock('../sections/SettingsSection', () => ({
  SettingsSection: () => <div data-testid="section-settings" />,
}));
vi.mock('../../../features/rules/RulesPanel', () => ({
  RulesPanel: ({ projectId }: { projectId: string }) => (
    <div data-testid="section-rules">{projectId}</div>
  ),
}));

import { GovernanceShell, auditProjectGovernancePageGovernance } from '../GovernanceShell';

function makeGovernance() {
  return {
    project: {
      id: 'p-1',
      name: 'Sage',
      path: '/w/sage',
      projectType: 'coding',
      projectStage: 'development',
      detectedType: null,
      vcsMode: 'git',
      allowedPaths: [],
      createdAt: 1,
      lastOpenedAt: 2,
      sessionCount: 0,
      lastSessionId: null,
      bootstrapState: { applied: [], appliedAt: null },
    },
    milestones: [],
    profileEntries: [],
    activeProjectType: 'coding',
    bootstrapProgress: { steps: [], done: 0, total: 5 },
    upcomingDeadline: null,
    scaffoldResult: null,
    scaffolding: false,
    startingSession: false,
    savingPaths: false,
    newAllowedPath: '',
    setNewAllowedPath: vi.fn(),
    savingProfile: false,
    profileCategory: 'convention',
    setProfileCategory: vi.fn(),
    profileDraft: '',
    setProfileDraft: vi.fn(),
    reload: vi.fn(),
    reloadMilestones: vi.fn(),
    changeProjectType: vi.fn(),
    changeProjectStage: vi.fn(),
    changeVcsMode: vi.fn(),
    scaffold: vi.fn(),
    startSession: vi.fn(),
    addProfileEntry: vi.fn(),
    deleteProfileEntry: vi.fn(),
    addAllowedPath: vi.fn(),
    quickAddPresetPath: vi.fn(),
    removeAllowedPath: vi.fn(),
  };
}

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/projects/governance/:projectId" element={<GovernanceShell />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  governance.mockReturnValue(makeGovernance());
});

describe('GovernanceShell', () => {
  it('renders five tabs and the overview section by default', () => {
    renderAt('/projects/governance/p-1');
    for (const id of ['overview', 'rules', 'knowledge', 'files', 'settings']) {
      expect(screen.getByTestId(`governance-tab-${id}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId('section-overview')).toBeInTheDocument();
  });

  it('maps legacy ?tab=playbook deep links to the rules tab', () => {
    renderAt('/projects/governance/p-1?tab=playbook');
    expect(screen.getByTestId('governance-tab-rules').className).toContain('bg-primary');
  });

  it('switches sections when a tab is clicked', () => {
    renderAt('/projects/governance/p-1');
    fireEvent.click(screen.getByTestId('governance-tab-files'));
    expect(screen.getByTestId('section-files')).toBeInTheDocument();
  });

  it('renders the rules panel on the rules tab', () => {
    renderAt('/projects/governance/p-1?tab=rules');
    expect(screen.getByTestId('section-rules').textContent).toBe('p-1');
  });

  it('shows the empty state when the project is missing', () => {
    governance.mockReturnValue({ ...makeGovernance(), project: null });
    renderAt('/projects/governance/p-1');
    expect(screen.getByTestId('governance-loading')).toBeInTheDocument();
  });
});

describe('auditProjectGovernancePageGovernance', () => {
  it('declares the new five-tab layout', () => {
    const audit = auditProjectGovernancePageGovernance();
    expect(audit.tabs).toEqual(['overview', 'rules', 'knowledge', 'files', 'settings']);
    expect(audit.module).toBe('src/pages/governance/GovernanceShell.tsx');
  });
});
