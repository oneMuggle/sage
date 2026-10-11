import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockList = vi.fn();
const mockUpdate = vi.fn();
const mockScaffold = vi.fn();
const mockUpdateAllowedPaths = vi.fn();
const mockListConstraints = vi.fn();
const mockListMilestones = vi.fn();
const mockGetGitStatus = vi.fn();
const mockGetContextBudget = vi.fn();
const mockGetWorkspaceOverview = vi.fn();
const mockAddMaterialFromFile = vi.fn();
const mockDiagnose = vi.fn();
const mockGetProjectProfile = vi.fn();
const mockCreateProjectProfile = vi.fn();

vi.mock('../../shared/api', () => ({
  projectApi: {
    list: (...args: unknown[]) => mockList(...args),
    update: (...args: unknown[]) => mockUpdate(...args),
    scaffold: (...args: unknown[]) => mockScaffold(...args),
    updateAllowedPaths: (...args: unknown[]) => mockUpdateAllowedPaths(...args),
    listConstraints: (...args: unknown[]) => mockListConstraints(...args),
    listMilestones: (...args: unknown[]) => mockListMilestones(...args),
    getGitStatus: (...args: unknown[]) => mockGetGitStatus(...args),
    getContextBudget: (...args: unknown[]) => mockGetContextBudget(...args),
    getWorkspaceOverview: (...args: unknown[]) => mockGetWorkspaceOverview(...args),
    addMaterialFromFile: (...args: unknown[]) => mockAddMaterialFromFile(...args),
    diagnose: (...args: unknown[]) => mockDiagnose(...args),
  },
  memoryApi: {
    getProjectProfile: (...args: unknown[]) => mockGetProjectProfile(...args),
    createProjectProfile: (...args: unknown[]) => mockCreateProjectProfile(...args),
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
  mockGetContextBudget.mockResolvedValue({
    projectId: 'proj-1',
    l1ConventionsChars: 420,
    l2MetadataChars: 120,
    l2ConstraintsChars: 180,
    l3ProfileChars: 240,
    l4MaterialsChars: 3200,
    totalChars: 4160,
    capChars: 16000,
    perFileCapChars: 8000,
    usageRatio: 0.26,
    activeMaterialsCount: 2,
    totalMaterialsCount: 3,
    enabledConstraintsCount: 3,
  });
  mockGetWorkspaceOverview.mockResolvedValue({
    projectId: 'proj-1',
    hasSageMd: true,
    hasHooksJson: false,
    codingIndicators: ['package.json', 'pyproject.toml'],
    officeDeliverables: [
      {
        name: '采购合同审阅意见书.docx',
        relativePath: '03_定稿与签发归档/采购合同审阅意见书.docx',
        ext: '.docx',
        category: 'Word 文书',
        sizeBytes: 24576,
        modifiedAt: 1700000000,
      },
    ],
    researchArtifacts: [
      {
        name: 'survey2026.pdf',
        relativePath: '01_literature/survey2026.pdf',
        ext: '.pdf',
        category: '文献 PDF',
        sizeBytes: 1048576,
        modifiedAt: 1700000000,
      },
    ],
    directorySummary: [
      { name: '00_立项与背景材料', fileCount: 2 },
      { name: '03_定稿与签发归档', fileCount: 1 },
    ],
  });
  mockGetProjectProfile.mockResolvedValue({
    project_key: 'D:/Archives/Contract2026',
    projects: ['D:/Archives/Contract2026'],
    categories: ['convention', 'architecture', 'decision', 'goal', 'note'],
    items: [
      {
        id: 'pf-1',
        content: 'RQ1: 验证多跳检索召回率 — HotpotQA 基准',
        category: 'goal',
        importance: 5,
      },
    ],
  });
  mockCreateProjectProfile.mockReset();
  mockDiagnose.mockResolvedValue({
    projectId: 'proj-1',
    level: 'satisfied',
    detectedLanguages: ['TypeScript/Node.js', 'Python'],
    availableRuntimes: ['node', 'python', 'git'],
    testCommands: ['npm run test', 'pytest'],
    hooksConfigExists: true,
    hooksCount: 2,
    hooksTrusted: true,
    recommendations: [],
  });
  mockAddMaterialFromFile.mockResolvedValue({
    id: 'mat-file-1',
    projectId: 'proj-1',
    sourceMessageId: null,
    contentHash: 'h-file',
    content: '[来源文件: 03_定稿与签批归档/采购合同审阅意见书.docx]',
    status: 'ready',
    wikiPagePath: null,
    errorMessage: null,
    createdAt: 1000,
    enabled: true,
  });
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

  it('renders 5-layer context budget watermark and polymorphic cards across business and research', async () => {
    mockList.mockResolvedValueOnce([SAMPLE_PROJECT]);
    mockUpdate.mockResolvedValueOnce({
      ...SAMPLE_PROJECT,
      projectType: 'research',
      projectStage: 'literature',
    });
    mockCreateProjectProfile.mockResolvedValueOnce({ id: 'pf-2', content: 'RQ2: 跨目录文献引文对齐精度 — BibTeX 校验集', category: 'goal', importance: 5 });

    render(<ProjectArchetypeStudio />);

    const budgetCard = await screen.findByTestId('context-budget-watermark-card');
    await waitFor(() => {
      expect(budgetCard.textContent).toContain('2/3 启用');
    });

    // Business polymorphic card is shown initially and supports one-click file pinning
    const businessCard = await screen.findByTestId('polymorphic-card-business');
    expect(businessCard.textContent).toContain('采购合同审阅意见书.docx');
    fireEvent.click(screen.getByTestId('pin-artifact-to-materials'));
    await waitFor(() => {
      expect(mockAddMaterialFromFile).toHaveBeenCalledWith(
        'proj-1',
        '03_定稿与签发归档/采购合同审阅意见书.docx',
      );
    });

    // Switch active project archetype to research
    const typeSelect = screen.getByLabelText('切换项目形态');
    fireEvent.change(typeSelect, { target: { value: 'research' } });

    const researchCard = await screen.findByTestId('polymorphic-card-research');
    expect(researchCard.textContent).toContain('survey2026.pdf');
    expect(researchCard.textContent).toContain('RQ1: 验证多跳检索召回率');

    // Add a new Research Question
    fireEvent.change(screen.getByTestId('research-rq-input'), {
      target: { value: 'RQ2: 跨目录文献引文对齐精度' },
    });
    fireEvent.change(screen.getByTestId('research-rq-reason'), {
      target: { value: 'BibTeX 校验集' },
    });
    fireEvent.click(screen.getByTestId('research-rq-add'));

    await waitFor(() => {
      expect(mockCreateProjectProfile).toHaveBeenCalledWith(
        'RQ2: 跨目录文献引文对齐精度 — BibTeX 校验集',
        {
          projectKey: 'D:/Archives/Contract2026',
          category: 'goal',
          importance: 5,
        },
      );
    });
  });
});
