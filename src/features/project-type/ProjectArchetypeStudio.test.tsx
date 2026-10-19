import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
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
const mockWikiScanFiles = vi.fn();
const mockWikiExtractSymbols = vi.fn();
const mockWikiGenerate = vi.fn();
const mockExtractKnowledge = vi.fn();
const mockConfirmKnowledge = vi.fn();
const mockSemanticSearchMaterials = vi.fn();
const mockGetIndexingStats = vi.fn();
const mockReindexMaterial = vi.fn();
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
    wikiScanFiles: (...args: unknown[]) => mockWikiScanFiles(...args),
    wikiExtractSymbols: (...args: unknown[]) => mockWikiExtractSymbols(...args),
    wikiGenerate: (...args: unknown[]) => mockWikiGenerate(...args),
    extractKnowledge: (...args: unknown[]) => mockExtractKnowledge(...args),
    confirmKnowledge: (...args: unknown[]) => mockConfirmKnowledge(...args),
    semanticSearchMaterials: (...args: unknown[]) => mockSemanticSearchMaterials(...args),
    getMaterialIndexingStats: (...args: unknown[]) => mockGetIndexingStats(...args),
    reindexMaterial: (...args: unknown[]) => mockReindexMaterial(...args),
  },
  memoryApi: {
    getProjectProfile: (...args: unknown[]) => mockGetProjectProfile(...args),
    createProjectProfile: (...args: unknown[]) => mockCreateProjectProfile(...args),
    deleteProjectProfile: (...args: unknown[]) => mockDeleteProjectProfile(...args),
  },
}));

import { ProjectArchetypeStudio } from './ProjectArchetypeStudio';
import { SemanticSearchPanel } from './SemanticSearchPanel';
import { StudioProfileTabPanel } from './StudioProfileTabPanel';

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
  mockWikiScanFiles.mockResolvedValue({
    files: [{ path: 'src/index.ts', language: 'typescript', sizeBytes: 2048 }],
  });
  mockWikiExtractSymbols.mockResolvedValue({
    symbols: [{ name: 'bootstrap', kind: 'function', file: 'src/index.ts', line: 1 }],
  });
  mockWikiGenerate.mockResolvedValue({
    pagesGenerated: 2,
    pagesUpdated: 0,
    pagesSkipped: 0,
    wikiPaths: ['wiki/README.md', 'wiki/ARCHITECTURE.md'],
    errors: [],
  });
  mockExtractKnowledge.mockResolvedValue({
    reasoning: '从法务会签对话提炼关键金额校核约定',
    entries: [
      {
        category: 'convention',
        content: '所有补充协议须附原始合同编号',
        importance: 8,
        reasoning: '保障归档可追溯性',
      },
    ],
  });
  mockConfirmKnowledge.mockResolvedValue({ addedCount: 1 });
  mockSemanticSearchMaterials.mockResolvedValue({
    results: [
      {
        materialId: 'mat-file-01',
        chunkIndex: 0,
        score: 0.92,
        content: 'HotpotQA 基准上多跳召回率提升 6.4%',
      },
    ],
  });
  mockGetIndexingStats.mockResolvedValue({
    totalMaterials: 3,
    indexedMaterials: 2,
    totalChunks: 12,
    embedderType: 'local',
  });
  mockReindexMaterial.mockResolvedValue({ chunkCount: 3 });
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
    render(
      <MemoryRouter>
        <ProjectArchetypeStudio />
      </MemoryRouter>,
    );

    // Default tab is coding
    expect(screen.getByTestId('archetype-blueprint-detail-coding')).toBeInTheDocument();
    expect(screen.getByText('src/')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('studio-copy-dirs-btn'));
    fireEvent.click(screen.getByTestId('studio-copy-stages-btn'));
    fireEvent.click(screen.getByTestId('studio-copy-pillars-btn'));
    fireEvent.click(screen.getByTestId('studio-copy-milestones-btn'));
    fireEvent.click(screen.getByTestId('studio-copy-subtemplates-btn'));
    fireEvent.click(screen.getByTestId('studio-copy-blueprint-md-btn'));
    expect(screen.getByTestId('studio-copy-blueprint-md-btn')).toHaveTextContent(/已复制蓝图 MD|复制当前蓝图 MD/);
    fireEvent.click(screen.getByTestId('studio-copy-all-blueprints-md-btn'));
    expect(screen.getByTestId('studio-copy-all-blueprints-md-btn')).toHaveTextContent(
      /已复制全形态对比|复制四大蓝图对比 MD/,
    );

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

  it('renders overview card with polymorphic widgets and enter-governance button', async () => {
    mockList.mockResolvedValueOnce([SAMPLE_PROJECT]);
    mockUpdate.mockResolvedValueOnce({
      ...SAMPLE_PROJECT,
      projectType: 'research',
      projectStage: 'literature',
    });
    mockCreateProjectProfile.mockResolvedValueOnce({
      id: 'pf-2',
      content: 'RQ2: 跨目录文献引文对齐精度 — BibTeX 校验集',
      category: 'goal',
      importance: 5,
    });

    render(
      <MemoryRouter>
        <ProjectArchetypeStudio />
      </MemoryRouter>,
    );

    const budgetCard = await screen.findByTestId('context-budget-watermark-card');
    await waitFor(() => {
      expect(budgetCard.textContent).toContain('2/3 启用');
    });

    // VCS checkpoint status is rendered by PolymorphicArchetypeCards
    expect(screen.getByTestId('vcs-checkpoint-status')).toHaveTextContent('VCS: 内置快照保护中');
    expect(await screen.findByTestId('workspace-vcs-summary-widget')).toBeInTheDocument();
    expect(await screen.findByTestId('workspace-charter-status-badge')).toBeInTheDocument();
    expect(screen.getByTestId('overview-quick-checkpoint-btn')).toBeInTheDocument();
    expect(await screen.findByTestId('project-advisor-card')).toBeInTheDocument();
    fireEvent.click(await screen.findByTestId('advisor-toggle-details-btn'));
    fireEvent.click(screen.getByTestId('advisor-batch-suggestions-to-constraint-btn'));
    expect(screen.getByTestId('advisor-batch-suggestions-to-constraint-btn')).toHaveTextContent('已全部转约束');
    fireEvent.click(screen.getByTestId('advisor-suggestion-to-l4-0'));
    expect(screen.getByTestId('advisor-suggestion-to-l4-0')).toHaveTextContent('已存L4');
    expect(screen.getByTestId('wiki-generation-panel')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('studio-quick-scaffold-btn'));
    expect(screen.getByTestId('studio-quick-scaffold-btn')).toHaveTextContent('已初始化脚手架');
    fireEvent.click(screen.getByTestId('studio-seed-recommended-milestones-btn'));
    expect(screen.getByTestId('studio-seed-recommended-milestones-btn')).toHaveTextContent('已播种里程碑');
    fireEvent.click(screen.getByTestId('studio-blueprint-to-constraint-btn'));
    expect(screen.getByTestId('studio-blueprint-to-constraint-btn')).toHaveTextContent('已转蓝图L2');
    fireEvent.click(screen.getByTestId('overview-pillars-to-milestone-btn'));
    expect(screen.getByTestId('overview-pillars-to-milestone-btn')).toHaveTextContent('已转支柱里程碑');
    fireEvent.click(screen.getByTestId('overview-copy-stages-btn'));
    fireEvent.click(screen.getByTestId('overview-stages-to-l3-btn'));
    expect(screen.getByTestId('overview-stages-to-l3-btn')).toHaveTextContent('已存管线L3');
    fireEvent.click(screen.getByTestId('overview-stages-to-l4-btn'));
    expect(screen.getByTestId('overview-stages-to-l4-btn')).toHaveTextContent('已存管线L4');
    fireEvent.click(screen.getByTestId('studio-copy-active-path-btn'));
    fireEvent.click(screen.getByTestId('studio-save-blueprint-l4-btn'));
    expect(screen.getByTestId('studio-save-blueprint-l4-btn')).toHaveTextContent('已存蓝图 L4');
    fireEvent.click(screen.getByTestId('studio-save-blueprint-l3-btn'));
    expect(screen.getByTestId('studio-save-blueprint-l3-btn')).toHaveTextContent('已存蓝图 L3');
    fireEvent.click(screen.getByTestId('wiki-preview-btn'));
    expect(await screen.findByTestId('wiki-copy-preview-btn')).toBeInTheDocument();
    expect(screen.getByTestId('wiki-symbol-preview-list')).toHaveTextContent('bootstrap');
    fireEvent.click(screen.getByTestId('wiki-lang-filter-typescript'));
    fireEvent.click(screen.getByTestId('wiki-lang-filter-all'));
    fireEvent.click(screen.getByTestId('wiki-symbol-to-constraint-0'));
    expect(screen.getByTestId('wiki-symbol-to-constraint-0')).toHaveTextContent('已护栏');
    fireEvent.click(screen.getByTestId('wiki-symbol-filter-function'));
    fireEvent.click(screen.getByTestId('wiki-symbol-filter-all'));
    fireEvent.click(screen.getByTestId('wiki-generate-btn'));
    expect(await screen.findByTestId('wiki-copy-manifest-btn')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('wiki-ingest-material-0'));
    await waitFor(() => {
      expect(mockAddMaterialFromFile).toHaveBeenCalledWith('proj-1', 'wiki/README.md');
    });

    // Quick import default constraints from ConstraintSummaryWidget empty state
    fireEvent.click(await screen.findByTestId('constraint-summary-quick-import'));
    await waitFor(() => {
      expect(mockImportConstraints).toHaveBeenCalledWith('proj-1', 'business');
    });

    // Verify refresh buttons and stage badge on ConstraintSummaryWidget & MilestoneProgressWidget
    expect(await screen.findByTestId('constraint-summary-refresh-btn')).toBeInTheDocument();
    expect(await screen.findByTestId('milestone-summary-refresh-btn')).toBeInTheDocument();
    expect(screen.getByTestId('milestone-summary-stage-ms-1')).toBeInTheDocument();

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
    fireEvent.click(screen.getByTestId('checkpoint-copy-timeline-btn'));
    fireEvent.click(screen.getByTestId('business-save-style-l3-btn'));
    expect(screen.getByTestId('business-style-applied-hint')).toHaveTextContent(
      '已沉淀文书规范至 L3',
    );
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

    // "进入治理" button navigates to governance page
    expect(screen.getByTestId('enter-governance-btn')).toBeInTheDocument();
  });

  it('supports SemanticSearchPanel pillar quick query & stats L3 archive, and StudioProfileTabPanel pillar append (Phase P58)', async () => {
    const onDraftChange = vi.fn();
    render(
      <div>
        <SemanticSearchPanel projectId="proj-1" projectType="research" />
        <StudioProfileTabPanel
          projectPath="D:/Archives/Contract2026"
          projectType="research"
          projectId="proj-1"
          profileEntries={[
            {
              id: 'pf-cat-1',
              category: 'convention',
              content: '引用必须包含 DOI',
              importance: 8,
              project_key: 'D:/Archives/Contract2026',
              source: 'manual',
              created_at: 1000,
              updated_at: 1000,
            },
          ]}
          profileCategory="convention"
          onCategoryChange={vi.fn()}
          profileDraft="初始画像规范"
          onDraftChange={onDraftChange}
          savingProfile={false}
          onAddEntry={vi.fn()}
          onDeleteEntry={vi.fn()}
        />
      </div>,
    );

    fireEvent.click(await screen.findByTestId('semantic-stats-save-l3-btn'));
    expect(screen.getByTestId('semantic-stats-save-l3-btn')).toHaveTextContent('已存统计 L3');
    fireEvent.click(screen.getByTestId('semantic-stats-save-l4-btn'));
    expect(screen.getByTestId('semantic-stats-save-l4-btn')).toHaveTextContent('已存统计 L4');
    fireEvent.click(screen.getByTestId('semantic-stats-copy-btn'));

    fireEvent.click(screen.getByTestId('semantic-pillar-query-0'));
    await waitFor(() => {
      expect(mockSemanticSearchMaterials).toHaveBeenCalledWith(
        'proj-1',
        'SAGE.md：核心研究问题 (RQ)、科学假设与数学符号规范表 (Notation)',
        10,
      );
    });
    fireEvent.click(screen.getByTestId('semantic-copy-query-btn'));
    fireEvent.click(screen.getByTestId('semantic-clear-query-btn'));
    expect(screen.getByTestId('semantic-search-input')).toHaveValue('');

    fireEvent.click(screen.getByTestId('studio-profile-pillar-append-0'));
    expect(onDraftChange).toHaveBeenCalledWith(
      '初始画像规范；SAGE.md：核心研究问题 (RQ)、科学假设与数学符号规范表 (Notation)',
    );
    fireEvent.click(screen.getByTestId('studio-profile-pillars-to-l4-btn'));
    expect(screen.getByTestId('studio-profile-pillars-to-l4-btn')).toHaveTextContent('已存支柱 L4');
    fireEvent.click(screen.getByTestId('studio-profile-cats-to-l4-btn'));
    expect(screen.getByTestId('studio-profile-cats-to-l4-btn')).toHaveTextContent('已存分布L4');
    const copySessionBtn = await screen.findByTestId('knowledge-copy-session-id-btn');
    fireEvent.click(copySessionBtn);
    fireEvent.click(screen.getByTestId('knowledge-extract-btn'));
    const reasoningMilestoneBtn = await screen.findByTestId('knowledge-reasoning-to-milestone-btn');
    fireEvent.click(reasoningMilestoneBtn);
    expect(screen.getByTestId('knowledge-reasoning-to-milestone-btn')).toHaveTextContent('已转里程碑');
  });
});
