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
const mockAddMaterial = vi.fn();
const mockDiagnose = vi.fn();
const mockCreateCheckpoint = vi.fn();
const mockRestoreCheckpoint = vi.fn();
const mockListMaterials = vi.fn();
const mockGetCharter = vi.fn();
const mockUpdateCharter = vi.fn();
const mockCreateConstraint = vi.fn();
const mockCreateMilestone = vi.fn();
const mockImportConstraints = vi.fn();
const mockUpdateMilestone = vi.fn();
const mockGetAdvice = vi.fn();
const mockListSessions = vi.fn();
const mockGetProjectProfile = vi.fn();
const mockCreateProjectProfile = vi.fn();
const mockDeleteProjectProfile = vi.fn();

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
    addMaterial: (...args: unknown[]) => mockAddMaterial(...args),
    diagnose: (...args: unknown[]) => mockDiagnose(...args),
    createCheckpoint: (...args: unknown[]) => mockCreateCheckpoint(...args),
    restoreCheckpoint: (...args: unknown[]) => mockRestoreCheckpoint(...args),
    listMaterials: (...args: unknown[]) => mockListMaterials(...args),
    getCharter: (...args: unknown[]) => mockGetCharter(...args),
    updateCharter: (...args: unknown[]) => mockUpdateCharter(...args),
    createConstraint: (...args: unknown[]) => mockCreateConstraint(...args),
    createMilestone: (...args: unknown[]) => mockCreateMilestone(...args),
    importConstraints: (...args: unknown[]) => mockImportConstraints(...args),
    updateMilestone: (...args: unknown[]) => mockUpdateMilestone(...args),
    getAdvice: (...args: unknown[]) => mockGetAdvice(...args),
    listSessions: (...args: unknown[]) => mockListSessions(...args),
  },
  memoryApi: {
    getProjectProfile: (...args: unknown[]) => mockGetProjectProfile(...args),
    createProjectProfile: (...args: unknown[]) => mockCreateProjectProfile(...args),
    deleteProjectProfile: (...args: unknown[]) => mockDeleteProjectProfile(...args),
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
  mockGetAdvice.mockResolvedValue({
    healthScore: 86,
    summary: '项目五层上下文结构完整，里程碑推进正常。',
    risks: [],
    suggestions: [{ priority: 'medium', action: '补充二审归档快照', reason: '定稿前保护' }],
  });
  mockListSessions.mockResolvedValue([
    { id: 'sess-contract-01', title: '法务条款一审对话', createdAt: 1000, updatedAt: 2000 },
  ]);
  mockImportConstraints.mockResolvedValue([
    {
      id: 'c-imp-1',
      projectId: 'proj-1',
      category: 'document_format',
      content: '公文格式规范',
      triggerPattern: '03_定稿与签发归档/**',
      priority: 8,
      enabled: true,
      createdAt: 1000,
    },
  ]);
  mockUpdateMilestone.mockResolvedValue({
    id: 'ms-1',
    projectId: 'proj-1',
    title: '完成法务合规会签',
    description: null,
    stage: 'monitoring',
    dueDate: '2026-10-15',
    completedAt: 2000,
    status: 'completed',
    sortOrder: 1,
    createdAt: 1000,
  });
  mockListMilestones.mockResolvedValue([
    {
      id: 'ms-1',
      projectId: 'proj-1',
      title: '完成法务合规会签',
      description: null,
      stage: 'monitoring',
      dueDate: '2026-10-15',
      completedAt: null,
      status: 'in_progress',
      sortOrder: 1,
      createdAt: 1000,
    },
  ]);
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
    recentCheckpoints: [
      {
        id: 'cp_1',
        label: '初稿备份',
        createdAt: 1500,
        fileCount: 2,
      },
    ],
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
  mockDeleteProjectProfile.mockReset();
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
  mockAddMaterial.mockResolvedValue({
    id: 'mat-text-1',
    projectId: 'proj-1',
    sourceMessageId: null,
    contentHash: 'h-text',
    content: '合同关键违约责任上限：不超过合同总额 20%',
    status: 'ready',
    wikiPagePath: null,
    errorMessage: null,
    createdAt: 1000,
    enabled: true,
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
    expect(screen.getByTestId('allowed-paths-copy-md-btn')).toBeInTheDocument();
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

    // Deadline countdown capsule & VCS mode status are rendered
    expect(await screen.findByTestId('project-deadline-capsule')).toHaveTextContent(
      '完成法务合规会签',
    );
    expect(screen.getByTestId('vcs-checkpoint-status')).toHaveTextContent(
      'VCS: 内置快照保护中',
    );
    expect(screen.getByTestId('studio-vcs-mode-select')).toHaveValue('builtin');
    expect(await screen.findByTestId('workspace-vcs-summary-widget')).toBeInTheDocument();
    expect(await screen.findByTestId('workspace-charter-status-badge')).toBeInTheDocument();
    expect(screen.getByTestId('overview-quick-checkpoint-btn')).toBeInTheDocument();
    expect(await screen.findByTestId('project-advisor-card')).toBeInTheDocument();
    expect(screen.getByTestId('wiki-generation-panel')).toBeInTheDocument();

    // Quick import default constraints from ConstraintSummaryWidget empty state
    fireEvent.click(await screen.findByTestId('constraint-summary-quick-import'));
    await waitFor(() => {
      expect(mockImportConstraints).toHaveBeenCalledWith('proj-1', 'business');
    });

    // Quick toggle milestone status from MilestoneProgressWidget
    fireEvent.click(await screen.findByTestId('milestone-quick-toggle-ms-1'));
    await waitFor(() => {
      expect(mockUpdateMilestone).toHaveBeenCalledWith('proj-1', 'ms-1', { status: 'completed' });
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

    // Business document style bar & quick checkpoint presets on the business card
    expect(screen.getByTestId('business-doc-style-bar')).toBeInTheDocument();
    expect(screen.getByTestId('checkpoint-quick-presets')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('business-apply-style-btn'));
    await waitFor(() => {
      expect(mockCreateConstraint).toHaveBeenCalledWith(
        'proj-1',
        expect.objectContaining({ category: 'document_format' }),
      );
    });

    // Create a builtin checkpoint snapshot on the business card
    fireEvent.change(screen.getByTestId('checkpoint-label-input'), {
      target: { value: '法务二审定稿前备份' },
    });
    fireEvent.click(screen.getByTestId('create-checkpoint-btn'));
    await waitFor(() => {
      expect(mockCreateCheckpoint).toHaveBeenCalledWith('proj-1', '法务二审定稿前备份');
    });
    fireEvent.click(screen.getByTestId('restore-checkpoint-cp_1'));
    await waitFor(() => {
      expect(mockRestoreCheckpoint).toHaveBeenCalledWith('proj-1', 'cp_1');
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

    // Expand M3 Advisor details and trigger M3->M1 suggestion decomposition dialog
    fireEvent.click(await screen.findByTestId('advisor-toggle-details-btn'));
    fireEvent.click(await screen.findByTestId('advisor-decompose-suggestion-0'));
    expect(await screen.findByTestId('decompose-archetype-presets')).toBeInTheDocument();
    expect(screen.getByTestId('decompose-requirement-input')).toHaveValue('补充二审归档快照');
    expect(screen.getByTestId('decompose-context-input')).toHaveValue('定稿前保护');
    fireEvent.click(screen.getByTestId('decompose-preset-0'));
    fireEvent.click(screen.getByText('取消'));

    // Apply academic citation style & writing tone on the research card
    fireEvent.change(screen.getByTestId('research-citation-style-select'), {
      target: { value: 'IEEE' },
    });
    fireEvent.click(screen.getByTestId('research-apply-style-btn'));
    await waitFor(() => {
      expect(mockCreateConstraint).toHaveBeenCalledWith(
        'proj-1',
        expect.objectContaining({
          category: 'academic_writing',
          priority: 8,
        }),
      );
    });

    // Switch to L4 Controlled Materials tab and import a file
    fireEvent.click(screen.getByTestId('studio-tab-materials'));
    await waitFor(() => {
      expect(screen.getByTestId('project-materials-studio-panel')).toBeInTheDocument();
      expect(screen.getByTestId('semantic-search-panel')).toBeInTheDocument();
      expect(screen.getByTestId('semantic-stats-refresh-btn')).toBeInTheDocument();
    });
    fireEvent.change(screen.getByTestId('studio-material-file-input'), {
      target: { value: '01_literature/references.bib' },
    });
    fireEvent.click(screen.getByTestId('studio-material-file-add'));
    await waitFor(() => {
      expect(mockAddMaterialFromFile).toHaveBeenCalledWith('proj-1', '01_literature/references.bib');
    });

    // Discoverable files bar & direct text snippet ingestion in L4 Materials
    expect(screen.getByTestId('studio-discoverable-files-bar')).toBeInTheDocument();
    fireEvent.change(screen.getByTestId('studio-material-text-input'), {
      target: { value: '合同关键违约责任上限：不超过合同总额 20%' },
    });
    fireEvent.click(screen.getByTestId('studio-material-text-add'));
    await waitFor(() => {
      expect(mockAddMaterial).toHaveBeenCalledWith('proj-1', {
        content: '合同关键违约责任上限：不超过合同总额 20%',
      });
    });

    // Switch to Constraints tab and test Glob trigger path tester
    fireEvent.click(screen.getByText('AI 行为约束规则'));
    await waitFor(() => {
      expect(screen.getByTestId('constraint-glob-tester-bar')).toBeInTheDocument();
    });
    fireEvent.change(screen.getByTestId('constraint-glob-test-input'), {
      target: { value: '02_审校与修订过程/合同.docx' },
    });
    expect(screen.getByTestId('constraint-glob-match-count')).toBeInTheDocument();

    // Switch to Milestones tab and seed recommended milestones for the active archetype
    fireEvent.click(screen.getByText('阶段与里程碑管理'));
    await waitFor(() => {
      expect(screen.getByTestId('seed-archetype-milestones-btn')).toBeInTheDocument();
      expect(screen.getByTestId('milestone-manager-progress')).toBeInTheDocument();
      expect(screen.getByTestId('milestone-stage-filter-bar')).toBeInTheDocument();
      expect(screen.getByTestId('milestone-copy-roadmap-btn')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('新建里程碑'));
    expect(await screen.findByTestId('milestone-editor-stage-presets')).toBeInTheDocument();
    fireEvent.click(screen.getByText('取消'));
    fireEvent.click(screen.getByTestId('seed-archetype-milestones-btn'));
    await waitFor(() => {
      expect(mockCreateMilestone).toHaveBeenCalled();
    });

    // Switch to L3 Project Profile governance tab and add a project convention entry
    mockCreateProjectProfile.mockResolvedValueOnce({
      id: 'pf-3',
      content: '实验随机种子统一固定为 42',
      category: 'convention',
      importance: 5,
    });
    fireEvent.click(screen.getByTestId('studio-tab-profile'));
    expect(await screen.findByTestId('project-profile-studio-panel')).toBeInTheDocument();
    expect(await screen.findByTestId('knowledge-session-select')).toBeInTheDocument();
    expect(screen.getByTestId('studio-profile-presets-bar')).toBeInTheDocument();
    expect(screen.getByTestId('studio-profile-copy-md-btn')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('studio-profile-preset-0'));
    fireEvent.change(screen.getByTestId('studio-profile-category'), {
      target: { value: 'convention' },
    });
    fireEvent.change(screen.getByTestId('studio-profile-input'), {
      target: { value: '实验随机种子统一固定为 42' },
    });
    fireEvent.click(screen.getByTestId('studio-profile-add-btn'));
    await waitFor(() => {
      expect(mockCreateProjectProfile).toHaveBeenCalledWith(
        '实验随机种子统一固定为 42',
        expect.objectContaining({
          projectKey: 'D:/Archives/Contract2026',
          category: 'convention',
          importance: 5,
        }),
      );
    });
  });
});
