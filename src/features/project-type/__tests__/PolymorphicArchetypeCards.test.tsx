// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { PolymorphicArchetypeCards } from '../PolymorphicArchetypeCards';

const getContextBudgetMock = vi.fn();
const diagnoseMock = vi.fn();
const getWorkspaceOverviewMock = vi.fn();
const getProjectProfileMock = vi.fn();

vi.mock('../../../shared/api', () => ({
  projectApi: {
    getContextBudget: (...args: unknown[]) => getContextBudgetMock(...args),
    diagnose: (...args: unknown[]) => diagnoseMock(...args),
    getWorkspaceOverview: (...args: unknown[]) => getWorkspaceOverviewMock(...args),
  },
  memoryApi: {
    getProjectProfile: (...args: unknown[]) => getProjectProfileMock(...args),
    createProjectProfile: vi.fn(),
  },
}));

const project = {
  id: 'p1',
  path: '/work/demo',
  name: 'demo',
  createdAt: 1,
  lastOpenedAt: 1,
  allowedPaths: [],
  sessionCount: 0,
  lastSessionId: null,
};

describe('PolymorphicArchetypeCards (coding)', () => {
  beforeEach(() => {
    getContextBudgetMock.mockReset();
    diagnoseMock.mockReset();
    getWorkspaceOverviewMock.mockReset();
    getProjectProfileMock.mockReset();
    getContextBudgetMock.mockResolvedValue({
      l1ConventionsChars: 100,
      l2MetadataChars: 20,
      l2ConstraintsChars: 30,
      l3ProfileChars: 40,
      l4MaterialsChars: 50,
      capChars: 16000,
      enabledConstraintsCount: 2,
      activeMaterialsCount: 1,
      totalMaterialsCount: 3,
      totalChars: 240,
      synthesizedPreview: 'preview',
    } as never);
    diagnoseMock.mockResolvedValue({
      level: 'satisfied',
      testCommands: ['npm test'],
      hooksConfigExists: true,
      hooksCount: 1,
    } as never);
    getWorkspaceOverviewMock.mockResolvedValue({
      hasSageMd: true,
      hasHooksJson: true,
      codingIndicators: ['package.json'],
      directorySummary: [{ name: 'src', fileCount: 10 }],
      officeDeliverables: [],
      researchArtifacts: [],
      recentCheckpoints: [],
      checkpointCount: 0,
    } as never);
    getProjectProfileMock.mockResolvedValue({
      items: [{ id: 'd1', content: '采用 SQLite WAL', category: 'decision' }],
    } as never);
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it('renders three plain-language sub-cards for coding projects', async () => {
    render(<PolymorphicArchetypeCards project={project} projectType="coding" />);

    await waitFor(() => expect(screen.getByText('项目结构')).toBeInTheDocument());
    expect(screen.getByText('常用命令')).toBeInTheDocument();
    expect(screen.getByText('技术决策记录（会随每轮会话自动告知 AI）')).toBeInTheDocument();
    expect(screen.getByText('工作区里的主要目录和工程标志文件。')).toBeInTheDocument();
    expect(screen.getByText('采用 SQLite WAL')).toBeInTheDocument();
  });

  it('copies a command to the clipboard and shows feedback', async () => {
    render(<PolymorphicArchetypeCards project={project} projectType="coding" />);

    const button = await screen.findByTestId('coding-command-copy');
    fireEvent.click(button);
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith('npm test'));
    expect(await screen.findByText('已复制')).toBeInTheDocument();
  });

  it('fills the decision input from an example chip', async () => {
    render(<PolymorphicArchetypeCards project={project} projectType="coding" />);

    fireEvent.click(await screen.findByText('所有 API 走 REST 不走 GraphQL'));
    expect(screen.getByTestId('polymorphic-decision-input')).toHaveValue(
      '所有 API 走 REST 不走 GraphQL',
    );
  });
});
