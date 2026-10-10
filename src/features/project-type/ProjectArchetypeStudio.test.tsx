import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockList = vi.fn();
const mockUpdate = vi.fn();
const mockScaffold = vi.fn();
const mockUpdateAllowedPaths = vi.fn();
const mockListConstraints = vi.fn();
const mockListMilestones = vi.fn();
const mockGetGitStatus = vi.fn();

vi.mock('../../shared/api', () => ({
  projectApi: {
    list: (...args: unknown[]) => mockList(...args),
    update: (...args: unknown[]) => mockUpdate(...args),
    scaffold: (...args: unknown[]) => mockScaffold(...args),
    updateAllowedPaths: (...args: unknown[]) => mockUpdateAllowedPaths(...args),
    listConstraints: (...args: unknown[]) => mockListConstraints(...args),
    listMilestones: (...args: unknown[]) => mockListMilestones(...args),
    getGitStatus: (...args: unknown[]) => mockGetGitStatus(...args),
  },
}));

import { ProjectArchetypeStudio } from './ProjectArchetypeStudio';

const SAMPLE_PROJECT = {
  id: 'proj-1',
  path: 'D:/Archives/Contract2026',
  name: 'Contract2026',
  createdAt: 1000,
  lastOpenedAt: 2000,
  sessionCount: 1,
  lastSessionId: 's-1',
  description: '年度采购案卷',
  instructions: null,
  allowedPaths: ['D:/Templates/Legal/**'],
  projectType: 'business' as const,
  projectStage: 'initiation',
  vcsMode: 'builtin',
  detectedType: 'business' as const,
};

beforeEach(() => {
  mockList.mockReset();
  mockUpdate.mockReset();
  mockScaffold.mockReset();
  mockUpdateAllowedPaths.mockReset();
  mockListConstraints.mockResolvedValue([]);
  mockListMilestones.mockResolvedValue([]);
  mockGetGitStatus.mockResolvedValue({
    isRepo: false,
    branch: null,
    dirtyCount: 0,
    aheadCount: 0,
    behindCount: 0,
    untrackedCount: 0,
    stagedCount: 0,
    recentCommits: [],
  });
});

afterEach(() => {
  cleanup();
});

describe('ProjectArchetypeStudio', () => {
  it('switches between coding, business, research, and personal archetype blueprints', async () => {
    mockList.mockResolvedValueOnce([]);
    render(<ProjectArchetypeStudio />);

    // Default tab is coding
    expect(screen.getByTestId('archetype-blueprint-detail-coding')).toBeInTheDocument();
    expect(screen.getByText('src/')).toBeInTheDocument();

    // Switch to business (general archive)
    fireEvent.click(screen.getByTestId('archetype-tab-business'));
    expect(screen.getByTestId('archetype-blueprint-detail-business')).toBeInTheDocument();
    expect(screen.getByText('01_原始依据与佐证/')).toBeInTheDocument();

    // Switch to research
    fireEvent.click(screen.getByTestId('archetype-tab-research'));
    expect(screen.getByTestId('archetype-blueprint-detail-research')).toBeInTheDocument();
    expect(screen.getByText('01_literature/')).toBeInTheDocument();
    expect(screen.getByText('03_manuscript/')).toBeInTheDocument();
  });

  it('scaffolds active project and manages allowed read-only paths', async () => {
    mockList.mockResolvedValueOnce([SAMPLE_PROJECT]);
    mockScaffold.mockResolvedValueOnce({
      project: { ...SAMPLE_PROJECT, projectStage: 'initiation' },
      createdDirectories: [
        '00_立项与背景材料',
        '01_原始依据与佐证',
        '02_编制中工作稿',
        '03_定稿与签发归档',
      ],
      createdFiles: ['SAGE.md'],
      importedConstraintsCount: 3,
      seededMilestonesCount: 3,
      recommendedTemplates: ['business', 'archive_dossier_cn'],
    });
    mockUpdateAllowedPaths.mockResolvedValueOnce([
      'D:/Templates/Legal/**',
      'E:/Regulations/2026/**',
    ]);

    render(<ProjectArchetypeStudio />);

    expect(await screen.findByTestId('project-governance-studio')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('studio-scaffold-btn'));
    expect(await screen.findByTestId('studio-scaffold-feedback')).toHaveTextContent(
      '新建目录 4 个',
    );
    expect(mockScaffold).toHaveBeenCalledWith(
      'proj-1',
      expect.objectContaining({ projectType: 'business', createDirectories: true }),
    );

    // Switch to allowed_paths tab and add a read-only reference directory
    fireEvent.click(screen.getByRole('button', { name: /跨目录只读白名单/ }));
    expect(await screen.findByTestId('project-allowed-paths-panel')).toBeInTheDocument();
    expect(screen.getByText('D:/Templates/Legal/**')).toBeInTheDocument();

    const input = screen.getByPlaceholderText(/输入外部只读参考目录路径/);
    fireEvent.change(input, { target: { value: 'E:/Regulations/2026/**' } });
    fireEvent.click(screen.getByRole('button', { name: /添加只读路径/ }));

    await waitFor(() =>
      expect(mockUpdateAllowedPaths).toHaveBeenCalledWith('proj-1', [
        'D:/Templates/Legal/**',
        'E:/Regulations/2026/**',
      ]),
    );
  });
});
