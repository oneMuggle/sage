/**
 * ProjectTypeBadge 组件测试 (2026-09-25; Phase P29 TypeDetectionPreview, ProjectTypeSelector, StudioProfileTabPanel & KnowledgeExtractionPanel)
 *
 * 项目类型分类系统 - Phase 4.6 & Phase P29
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { projectApi } from '../../shared/api';

import { KnowledgeExtractionPanel } from './KnowledgeExtractionPanel';
import { ProjectTypeBadge } from './ProjectTypeBadge';
import { ProjectTypeSelector } from './ProjectTypeSelector';
import { SemanticSearchPanel } from './SemanticSearchPanel';
import { StudioProfileTabPanel } from './StudioProfileTabPanel';
import { TypeDetectionPreview } from './TypeDetectionPreview';
import { WikiGenerationPanel } from './WikiGenerationPanel';

vi.mock('../../shared/api', async () => {
  const actual = await vi.importActual<typeof import('../../shared/api')>('../../shared/api');
  return {
    ...actual,
    projectApi: {
      ...actual.projectApi,
      detectType: vi.fn(),
      listSessions: vi.fn().mockResolvedValue([]),
      extractKnowledge: vi.fn(),
      confirmKnowledge: vi.fn(),
      createConstraint: vi.fn().mockResolvedValue({}),
      getMaterialIndexingStats: vi.fn().mockResolvedValue({
        totalMaterials: 3,
        indexedMaterials: 3,
        pendingMaterials: 0,
        failedMaterials: 0,
        totalChunks: 12,
        embedderType: 'local',
        embedderDims: 384,
      }),
      semanticSearchMaterials: vi.fn().mockResolvedValue({
        results: [
          { materialId: 'mat-high', chunkIndex: 0, score: 0.85, content: '高相似度实验结论' },
          { materialId: 'mat-low', chunkIndex: 1, score: 0.42, content: '低相似度背景摘录' },
        ],
      }),
      wikiScanFiles: vi.fn().mockResolvedValue({
        files: [
          { path: 'src/core.ts', language: 'typescript', sizeBytes: 2048 },
          { path: 'scripts/run.py', language: 'python', sizeBytes: 1024 },
        ],
      }),
      wikiExtractSymbols: vi.fn().mockResolvedValue({
        symbols: [{ name: 'initCore', kind: 'function', filePath: 'src/core.ts', line: 1 }],
      }),
      wikiGenerate: vi.fn().mockResolvedValue({
        pagesGenerated: 2,
        pagesUpdated: 0,
        pagesSkipped: 0,
        wikiPaths: ['wiki/README.md', 'wiki/ARCHITECTURE.md'],
        errors: [],
      }),
      addMaterialFromFile: vi.fn().mockResolvedValue({}),
    },
  };
});

describe('ProjectTypeBadge', () => {
  it('renders coding type with correct label and icon', () => {
    render(<ProjectTypeBadge type="coding" />);
    expect(screen.getByText('编码')).toBeInTheDocument();
  });

  it('renders research type with correct label', () => {
    render(<ProjectTypeBadge type="research" />);
    expect(screen.getByText('科研')).toBeInTheDocument();
  });

  it('renders business type with correct label', () => {
    render(<ProjectTypeBadge type="business" />);
    expect(screen.getByText('事务')).toBeInTheDocument();
  });

  it('renders personal type with correct label', () => {
    render(<ProjectTypeBadge type="personal" />);
    expect(screen.getByText('个人')).toBeInTheDocument();
  });

  it('renders "未分类" when type is null', () => {
    render(<ProjectTypeBadge type={null} />);
    expect(screen.getByText('未分类')).toBeInTheDocument();
  });

  it('renders "未分类" when type is undefined', () => {
    render(<ProjectTypeBadge type={undefined} />);
    expect(screen.getByText('未分类')).toBeInTheDocument();
  });

  it('applies detected ring when detected prop is true', () => {
    const { container } = render(<ProjectTypeBadge type="coding" detected />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain('ring');
  });

  it('does not apply detected ring when detected is false', () => {
    const { container } = render(<ProjectTypeBadge type="coding" detected={false} />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).not.toContain('ring-1');
  });

  it('accepts custom className', () => {
    const { container } = render(<ProjectTypeBadge type="coding" className="custom-class" />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain('custom-class');
  });
});

describe('TypeDetectionPreview & ProjectTypeSelector (Phase P29)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders detected blueprint preview, stage pipeline, governance stats, and supports markdown copy & one-click apply', () => {
    const onApply = vi.fn();
    render(
      <TypeDetectionPreview
        result={{
          detectedType: 'research',
          confidence: 0.88,
          signals: ['发现 .bib 与 .tex 文件'],
        }}
        selectedType="coding"
        onApplyDetectedType={onApply}
      />,
    );

    expect(screen.getByTestId('detection-blueprint-preview')).toBeInTheDocument();
    expect(screen.getByTestId('detection-stages-preview')).toBeInTheDocument();
    expect(screen.getByTestId('detection-governance-stats')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('detection-copy-md-btn'));
    fireEvent.click(screen.getByTestId('detection-copy-signal-0'));
    fireEvent.click(screen.getByTestId('detection-copy-stages-btn'));
    fireEvent.click(screen.getByTestId('detection-copy-dirs-btn'));
    fireEvent.click(screen.getByTestId('detection-copy-suite-btn'));
    fireEvent.click(screen.getByTestId('detection-details-toggle-btn'));
    expect(screen.getByTestId('detection-details-panel')).toHaveTextContent('推荐规范包：');
    fireEvent.click(screen.getByTestId('detection-copy-pillars-btn'));
    fireEvent.click(screen.getByTestId('detection-copy-milestones-btn'));

    const applyBtn = screen.getByTestId('apply-detected-type-btn');
    fireEvent.click(applyBtn);
    expect(onApply).toHaveBeenCalledWith('research');
  });

  it('supports ProjectTypeSelector redetect and apply detected type when confidence is below auto-select threshold', async () => {
    vi.mocked(projectApi.detectType).mockResolvedValue({
      detectedType: 'business',
      confidence: 0.55,
      signals: ['发现合同模板目录'],
    });
    const onSelect = vi.fn();

    render(
      <ProjectTypeSelector
        open={true}
        onOpenChange={vi.fn()}
        projectPath="/workspace/contracts"
        onSelect={onSelect}
      />,
    );

    const applyDetectedBtn = await screen.findByTestId('selector-apply-detected-btn');
    fireEvent.click(applyDetectedBtn);

    expect(screen.getByTestId('selector-selected-summary')).toHaveTextContent('一般档案与文书');
    fireEvent.click(screen.getByTestId('selector-copy-blueprint-btn'));
    fireEvent.click(screen.getByTestId('selector-suite-toggle-btn'));
    expect(screen.getByTestId('selector-suite-details')).toHaveTextContent('细分规范包：');
    fireEvent.click(screen.getByTestId('selector-copy-subtemplates-btn'));
    fireEvent.click(screen.getByTestId('selector-copy-milestones-btn'));
    fireEvent.click(screen.getByTestId('selector-copy-pillars-btn'));
    fireEvent.click(screen.getByTestId('selector-copy-signal-0'));
    fireEvent.click(screen.getByTestId('selector-copy-detection-btn'));

    fireEvent.click(screen.getByTestId('selector-redetect-btn'));
    await waitFor(() => expect(projectApi.detectType).toHaveBeenCalledTimes(2));

    fireEvent.click(screen.getByRole('button', { name: '确认选择' }));
    expect(onSelect).toHaveBeenCalledWith('business');
  });
});

describe('StudioProfileTabPanel & KnowledgeExtractionPanel (Phase P29)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('supports StudioProfileTabPanel keyword search, category filter, and clear filter', () => {
    render(
      <StudioProfileTabPanel
        projectPath="/workspace/sage"
        projectType="coding"
        projectId="proj-p38"
        profileEntries={[
          {
            id: 'e-1',
            project_key: '/workspace/sage',
            category: 'convention',
            content: '单文件严格保持 <= 800 行',
            importance: 8,
            source: 'manual',
            created_at: 1,
            updated_at: 1,
          },
          {
            id: 'e-2',
            project_key: '/workspace/sage',
            category: 'architecture',
            content: 'IPC 契约一致性检查',
            importance: 9,
            source: 'manual',
            created_at: 2,
            updated_at: 2,
          },
        ]}
        profileCategory="convention"
        onCategoryChange={vi.fn()}
        profileDraft=""
        onDraftChange={vi.fn()}
        savingProfile={false}
        onAddEntry={vi.fn()}
        onDeleteEntry={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId('studio-profile-filter-architecture'));
    expect(screen.getByText('IPC 契约一致性检查')).toBeInTheDocument();
    expect(screen.queryByText('单文件严格保持 <= 800 行')).toBeNull();

    fireEvent.change(screen.getByTestId('studio-profile-search-input'), {
      target: { value: '不存在的关键词' },
    });
    fireEvent.click(screen.getByTestId('studio-profile-clear-filter'));
    expect(screen.getByText('单文件严格保持 <= 800 行')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('studio-profile-copy-entry-e-1'));
    fireEvent.click(screen.getByTestId('studio-profile-batch-promote-btn'));
    expect(screen.getByTestId('studio-profile-to-constraint-e-1')).toHaveTextContent('已升格约束');
    fireEvent.click(screen.getByTestId('studio-profile-to-l4-e-1'));
    expect(screen.getByTestId('studio-profile-to-l4-e-1')).toHaveTextContent('已存L4');
    fireEvent.click(screen.getByTestId('studio-profile-batch-milestone-btn'));
    expect(screen.getByTestId('studio-profile-to-milestone-e-1')).toHaveTextContent('已转里程碑');
  });

  it('supports KnowledgeExtractionPanel session refresh and extracted proposals markdown copy', async () => {
    vi.mocked(projectApi.listSessions).mockResolvedValue([
      {
        id: 'sess-p29',
        title: '研究计划讨论',
        created_at: 1,
        updated_at: 2,
        last_message_at: 2,
        message_count: 6,
        is_pinned: false,
      },
    ]);
    vi.mocked(projectApi.extractKnowledge).mockResolvedValue({
      projectKey: '/workspace/sage',
      reasoning: '从对话中提炼出实验可复现性规范',
      entries: [
        {
          category: 'convention',
          content: '固定随机种子为 42',
          importance: 9,
          reasoning: '保障消融实验可复现',
          sourceMessageIds: ['m-1'],
        },
      ],
    });

    render(<KnowledgeExtractionPanel projectId="proj-p29" />);
    await waitFor(() => expect(projectApi.listSessions).toHaveBeenCalledWith('proj-p29'));

    fireEvent.click(screen.getByTestId('knowledge-refresh-sessions-btn'));
    await waitFor(() => expect(projectApi.listSessions).toHaveBeenCalledTimes(2));

    fireEvent.click(screen.getByTestId('knowledge-extract-btn'));
    const copyMdBtn = await screen.findByTestId('knowledge-copy-md-btn');
    fireEvent.click(copyMdBtn);
    expect(screen.getByText('固定随机种子为 42')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('knowledge-category-filter-convention'));
    fireEvent.click(screen.getByTestId('knowledge-category-filter-all'));
    fireEvent.click(screen.getByTestId('knowledge-batch-to-constraint-btn'));
    expect(screen.getByTestId('knowledge-to-constraint-0')).toHaveTextContent('已转 L2 约束');
    fireEvent.click(screen.getByTestId('knowledge-batch-to-l4-btn'));
    expect(screen.getByTestId('knowledge-to-l4-0')).toHaveTextContent('已存L4');
  });
});

describe('SemanticSearchPanel & WikiGenerationPanel (Phase P31)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('supports SemanticSearchPanel similarity threshold filter and M4 -> L3 profile entry save', async () => {
    render(<SemanticSearchPanel projectId="proj-p31" projectType="research" />);

    fireEvent.click(screen.getByTestId('semantic-preset-0'));
    await waitFor(() => {
      expect(screen.getByText('高相似度实验结论')).toBeInTheDocument();
      expect(screen.getByText('低相似度背景摘录')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('semantic-score-filter-75'));
    expect(screen.getByText('高相似度实验结论')).toBeInTheDocument();
    expect(screen.queryByText('低相似度背景摘录')).toBeNull();

    fireEvent.click(screen.getByTestId('semantic-hit-save-profile-0'));
    await waitFor(() => {
      expect(projectApi.confirmKnowledge).toHaveBeenCalledWith('proj-p31', {
        entries: [
          expect.objectContaining({
            category: 'note',
            content: '高相似度实验结论',
          }),
        ],
      });
      expect(screen.getByTestId('semantic-hit-save-profile-0')).toHaveTextContent('已沉淀 L3');
    });

    fireEvent.click(screen.getByTestId('semantic-score-filter-0'));
    fireEvent.click(screen.getByTestId('semantic-batch-save-profile-btn'));
    await waitFor(() => {
      expect(screen.getByTestId('semantic-hit-save-profile-1')).toHaveTextContent('已沉淀 L3');
    });
    fireEvent.click(screen.getByTestId('semantic-hit-to-l4-0'));
    expect(screen.getByTestId('semantic-hit-to-l4-0')).toHaveTextContent('已存L4');
    fireEvent.click(screen.getByTestId('semantic-batch-to-milestone-btn'));
    expect(screen.getByTestId('semantic-hit-to-milestone-0')).toHaveTextContent('已转里程碑');
    fireEvent.click(screen.getByTestId('semantic-clear-results-btn'));
    expect(screen.queryByText('高相似度实验结论')).toBeNull();
  });

  it('supports WikiGenerationPanel preview file filter and batch ingest all to L4 Materials', async () => {
    render(<WikiGenerationPanel projectId="proj-p31" projectType="coding" />);

    fireEvent.click(screen.getByTestId('wiki-preview-btn'));
    const filterInput = await screen.findByTestId('wiki-preview-filter-input');
    fireEvent.click(screen.getByTestId('wiki-copy-symbols-btn'));
    fireEvent.click(screen.getByTestId('wiki-save-symbols-profile-btn'));
    await waitFor(() => {
      expect(screen.getByTestId('wiki-save-symbols-profile-btn')).toHaveTextContent('已沉淀符号至 L3');
    });
    fireEvent.click(screen.getByTestId('wiki-symbol-to-milestone-0'));
    expect(screen.getByTestId('wiki-symbol-to-milestone-0')).toHaveTextContent('已建里程碑');
    fireEvent.click(screen.getByTestId('wiki-symbol-to-l3-0'));
    expect(screen.getByTestId('wiki-symbol-to-l3-0')).toHaveTextContent('已存L3');
    fireEvent.click(screen.getByTestId('wiki-file-to-l4-src/core.ts'));
    expect(screen.getByTestId('wiki-file-to-l4-src/core.ts')).toHaveTextContent('已入库L4');
    fireEvent.change(filterInput, { target: { value: 'python' } });
    expect(screen.getByText('scripts/run.py')).toBeInTheDocument();
    expect(screen.queryByText('src/core.ts')).toBeNull();

    fireEvent.click(screen.getByTestId('wiki-generate-btn'));
    const ingestAllBtn = await screen.findByTestId('wiki-ingest-all-btn');
    fireEvent.click(ingestAllBtn);
    fireEvent.click(screen.getByTestId('wiki-save-manifest-l3-btn'));
    expect(screen.getByTestId('wiki-save-manifest-l3-btn')).toHaveTextContent('已沉淀至 L3');

    await waitFor(() => {
      expect(projectApi.addMaterialFromFile).toHaveBeenCalledWith('proj-p31', 'wiki/README.md');
      expect(projectApi.addMaterialFromFile).toHaveBeenCalledWith(
        'proj-p31',
        'wiki/ARCHITECTURE.md',
      );
      expect(screen.getByTestId('wiki-ingest-all-btn')).toHaveTextContent('已全部纳入 L4');
    });
  });
});
