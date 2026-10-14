/**
 * MilestoneProgressWidget 组件测试 (2026-09-25)
 *
 * 项目类型分类系统 - Phase 4.6
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { projectApi } from '../../shared/api';
import { I18nProvider } from '../../shared/lib/i18n';
import { ProjectMaterialsPanel, ProjectOverviewPanel } from '../../widgets/sidebar/sections/ProjectExpandedPanels';

import { MilestoneEditor } from './MilestoneEditor';
import { MilestoneManager } from './MilestoneManager';
import { MilestoneProgressWidget } from './MilestoneProgressWidget';
import { ProjectCreationWizard } from './ProjectCreationWizard';
import { ProjectOverviewWidgets } from './ProjectOverviewWidgets';

// Mock projectApi
vi.mock('../../shared/api', () => ({
  projectApi: {
    listMilestones: vi.fn(),
    createMilestone: vi.fn().mockResolvedValue({}),
    detectType: vi.fn().mockResolvedValue({
      detectedType: 'research',
      confidence: 0.9,
      signals: ['papers/', 'references.bib'],
    }),
    register: vi.fn().mockResolvedValue({
      id: 'proj-wiz-1',
      name: 'research-lab',
      path: '/workspace/research-lab',
      projectType: 'research',
    }),
    scaffold: vi.fn().mockResolvedValue({
      project: {
        id: 'proj-wiz-1',
        name: 'research-lab',
        path: '/workspace/research-lab',
        projectType: 'research',
      },
      createdDirectories: ['literature'],
      sageMdCreated: true,
      importedConstraints: 2,
      seededMilestones: 3,
    }),
    importConstraints: vi.fn().mockResolvedValue([]),
    update: vi.fn().mockImplementation(async (_id, patch) => ({
      id: 'proj-wiz-1',
      name: 'research-lab',
      path: '/workspace/research-lab',
      projectType: 'research',
      description: patch.description,
      instructions: patch.instructions,
      vcsMode: patch.vcs_mode,
    })),
    createCheckpoint: vi.fn().mockResolvedValue({ id: 'cp-init' }),
    decomposePreview: vi.fn().mockResolvedValue({
      reasoning: '按科研生命周期拆解',
      totalCount: 2,
      milestones: [
        { title: '主实验复现', description: '运行 baseline', stage: 'experiment', estimatedDays: 3, children: [] },
        { title: '消融分析', description: '对比核心模块', stage: 'experiment', estimatedDays: 2, children: [] },
      ],
    }),
    decomposeApply: vi.fn().mockResolvedValue([]),
  },
}));

const mockListMilestones = vi.mocked(projectApi.listMilestones);

describe('MilestoneProgressWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows loading state initially', () => {
    mockListMilestones.mockImplementation(() => new Promise(() => {}));

    render(<MilestoneProgressWidget projectId="test-project" />);
    expect(screen.getByText('加载中...')).toBeInTheDocument();
  });

  it('shows empty state when no milestones', async () => {
    mockListMilestones.mockResolvedValue([]);

    render(<MilestoneProgressWidget projectId="test-project" />);

    await waitFor(() => {
      expect(screen.getByText(/暂无里程碑/)).toBeInTheDocument();
    });
  });

  it('calculates progress correctly', async () => {
    mockListMilestones.mockResolvedValue([
      {
        id: 'm1',
        projectId: 'test-project',
        title: 'Milestone 1',
        status: 'completed',
        sortOrder: 1,
        createdAt: 1000,
      },
      {
        id: 'm2',
        projectId: 'test-project',
        title: 'Milestone 2',
        status: 'completed',
        sortOrder: 2,
        createdAt: 1000,
      },
      {
        id: 'm3',
        projectId: 'test-project',
        title: 'Milestone 3',
        status: 'pending',
        sortOrder: 3,
        createdAt: 1000,
      },
      {
        id: 'm4',
        projectId: 'test-project',
        title: 'Milestone 4',
        status: 'in_progress',
        sortOrder: 4,
        createdAt: 1000,
      },
    ]);

    render(<MilestoneProgressWidget projectId="test-project" />);

    await waitFor(() => {
      // 2 completed out of 4 = 50%
      expect(screen.getByText('50%')).toBeInTheDocument();
    });
  });

  it('displays status counts correctly', async () => {
    mockListMilestones.mockResolvedValue([
      {
        id: 'm1',
        projectId: 'test-project',
        title: 'Milestone 1',
        status: 'completed',
        sortOrder: 1,
        createdAt: 1000,
      },
      {
        id: 'm2',
        projectId: 'test-project',
        title: 'Milestone 2',
        status: 'in_progress',
        sortOrder: 2,
        createdAt: 1000,
      },
      {
        id: 'm3',
        projectId: 'test-project',
        title: 'Milestone 3',
        status: 'blocked',
        sortOrder: 3,
        createdAt: 1000,
      },
    ]);

    render(<MilestoneProgressWidget projectId="test-project" />);

    await waitFor(() => {
      // Check for status labels with counts
      expect(screen.getByText('完成：')).toBeInTheDocument();
      expect(screen.getByText('进行：')).toBeInTheDocument();
      expect(screen.getByText('阻塞：')).toBeInTheDocument();
    });
  });

  it('displays recent milestones with due dates', async () => {
    mockListMilestones.mockResolvedValue([
      {
        id: 'm1',
        projectId: 'test-project',
        title: 'MVP Release',
        status: 'in_progress',
        dueDate: '2026-10-15',
        sortOrder: 1,
        createdAt: 1000,
      },
      {
        id: 'm2',
        projectId: 'test-project',
        title: 'Beta Testing',
        status: 'pending',
        dueDate: '2026-11-01',
        sortOrder: 2,
        createdAt: 1000,
      },
    ]);

    render(<MilestoneProgressWidget projectId="test-project" />);

    await waitFor(() => {
      expect(screen.getByText('MVP Release')).toBeInTheDocument();
      expect(screen.getByText('Beta Testing')).toBeInTheDocument();
      expect(screen.getByText('截止：2026-10-15')).toBeInTheDocument();
      expect(screen.getByText('截止：2026-11-01')).toBeInTheDocument();
    });
  });

  it('shows error message on API failure', async () => {
    mockListMilestones.mockRejectedValue(new Error('Failed to load'));

    render(<MilestoneProgressWidget projectId="test-project" />);

    await waitFor(() => {
      expect(screen.getByText('Failed to load')).toBeInTheDocument();
    });
  });

  it('renders MilestoneEditor archetype deliverable templates and relative due-date presets (Phase P26)', async () => {
    render(
      <MilestoneEditor
        open={true}
        onOpenChange={vi.fn()}
        projectId="test-project"
        projectType="research"
        milestone={null}
        onSave={vi.fn()}
      />,
    );

    expect(screen.getByTestId('milestone-editor-templates')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('milestone-template-0'));
    fireEvent.click(screen.getByTestId('milestone-due-plus-7'));
    expect(screen.getByTestId('milestone-due-clear')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => {
      expect(projectApi.createMilestone).toHaveBeenCalledWith(
        'test-project',
        expect.objectContaining({
          title: '完成核心文献综述与研究假设形式化',
          stage: 'literature',
          sortOrder: 1,
        }),
      );
    });
  });

  it('fills L2 goal and instructions presets in ProjectCreationWizard confirm step (Phase P26)', async () => {
    render(<ProjectCreationWizard open={true} onOpenChange={vi.fn()} />);

    const pathInput = screen.getByPlaceholderText(/点击右侧按钮选择文件夹/);
    fireEvent.change(pathInput, { target: { value: '/workspace/research-lab' } });
    fireEvent.click(screen.getByRole('button', { name: /下一步/ }));

    await waitFor(() => {
      expect(screen.getByTestId('wizard-archetype-research')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: /下一步/ }));

    const presetBtn = await screen.findByTestId('wizard-goal-preset-0');
    fireEvent.click(presetBtn);

    expect(screen.getByTestId('wizard-description-input')).toHaveValue(
      '学术论文撰述、定量对比实验与可复现消融分析',
    );
    expect(screen.getByTestId('wizard-instructions-input')).toHaveValue(
      '采用严谨客观的学术被动语态，所有文献引用必须真实可查，固定并记录全部实验随机种子。',
    );

    fireEvent.click(screen.getByRole('button', { name: /创建项目/ }));
    await waitFor(() => {
      expect(projectApi.update).toHaveBeenCalledWith(
        'proj-wiz-1',
        expect.objectContaining({
          description: '学术论文撰述、定量对比实验与可复现消融分析',
          instructions: '采用严谨客观的学术被动语态，所有文献引用必须真实可查，固定并记录全部实验随机种子。',
        }),
      );
    });
  });

  it('supports MilestoneManager status filter, per-milestone subtask decompose, and TaskDecomposeDialog selective apply & markdown copy (Phase P27)', async () => {
    mockListMilestones.mockResolvedValue([
      {
        id: 'ms-p27-1',
        projectId: 'test-project',
        title: '完成主实验复现与消融对比',
        description: '验证多数据集指标',
        stage: 'experiment',
        status: 'in_progress',
        sortOrder: 1,
        createdAt: 1000,
      },
    ]);

    render(<MilestoneManager projectId="test-project" projectType="research" />);

    const statusBtn = await screen.findByTestId('milestone-status-filter-in_progress');
    fireEvent.click(statusBtn);
    expect(screen.getByText('完成主实验复现与消融对比')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('milestone-decompose-ms-p27-1'));
    expect(await screen.findByTestId('decompose-requirement-input')).toHaveValue(
      '完成主实验复现与消融对比',
    );

    fireEvent.click(screen.getByTestId('decompose-preview-btn'));
    const copyPlanBtn = await screen.findByTestId('decompose-copy-md-btn');
    fireEvent.click(copyPlanBtn);

    // Deselect second milestone node and apply only first node
    fireEvent.click(screen.getByTestId('decompose-node-checkbox-1'));
    fireEvent.click(screen.getByTestId('decompose-apply-btn'));

    await waitFor(() => {
      expect(projectApi.decomposeApply).toHaveBeenCalledWith('test-project', {
        milestones: [
          expect.objectContaining({ title: '主实验复现' }),
        ],
      });
    });
  });

  it('supports ProjectOverviewWidgets direct AI task decompose trigger and overview markdown copy (Phase P28)', async () => {
    render(
      <ProjectOverviewWidgets
        project={{
          id: 'test-project',
          name: 'SageGovernance',
          path: '/workspace/sage',
          projectType: 'research',
          projectStage: 'experiment',
          vcsMode: 'builtin',
          createdAt: 1000,
          lastOpenedAt: 2000,
          sessionCount: 3,
          lastSessionId: 's-1',
          allowedPaths: [],
        }}
      />,
    );

    const copyBtn = await screen.findByTestId('overview-copy-summary-md-btn');
    fireEvent.click(copyBtn);

    const decomposeBtn = screen.getByTestId('overview-open-decompose-btn');
    fireEvent.click(decomposeBtn);
    expect(await screen.findByTestId('decompose-requirement-input')).toBeInTheDocument();
  });

  it('supports MilestoneProgressWidget overdue warning badge & progress Markdown export, and ProjectExpandedPanels L2 presets & L4 search/export (Phase P30)', async () => {
    mockListMilestones.mockResolvedValue([
      {
        id: 'm-overdue-1',
        projectId: 'test-project',
        title: '历史逾期节点',
        status: 'in_progress',
        dueDate: '2020-01-01',
        stage: 'experiment',
        sortOrder: 1,
        createdAt: 1000,
      },
    ]);

    const onChange = vi.fn();
    render(
      <I18nProvider>
        <ProjectOverviewPanel
          project={{
            id: 'p-1',
            name: 'LabProject',
            path: '/workspace/lab',
            projectType: 'research',
            createdAt: 1000,
            lastOpenedAt: 2000,
            sessionCount: 1,
            lastSessionId: null,
            allowedPaths: [],
          }}
          draft={{ description: '', instructions: '', dirty: false }}
          saving={false}
          onSave={vi.fn()}
          onChange={onChange}
        />
        <ProjectMaterialsPanel
          project={{
            id: 'p-1',
            name: 'LabProject',
            path: '/workspace/lab',
            projectType: 'research',
            createdAt: 1000,
            lastOpenedAt: 2000,
            sessionCount: 1,
            lastSessionId: null,
            allowedPaths: [],
          }}
          list={[
            {
              id: 'mat-1',
              projectId: 'p-1',
              status: 'ready',
              content: 'Transformer 消融实验核心超参表',
              sourceMessageId: null,
              contentHash: 'h1',
              wikiPagePath: null,
              errorMessage: null,
              createdAt: 1000,
              enabled: true,
            },
            {
              id: 'mat-2',
              projectId: 'p-1',
              status: 'ready',
              content: '无关基线日志记录',
              sourceMessageId: null,
              contentHash: 'h2',
              wikiPagePath: null,
              errorMessage: null,
              createdAt: 1000,
              enabled: true,
            },
          ]}
          isLoading={false}
          isAdding={false}
          draftText=""
          currentSessionId={null}
          savingAnswer={false}
          removingMaterialId={null}
          onSaveAnswer={vi.fn()}
          onRemoveMaterial={vi.fn()}
          onDraftChange={vi.fn()}
          onAddMaterial={vi.fn()}
        />
      </I18nProvider>,
    );

    const overdueBadge = await screen.findByTestId('milestone-summary-overdue-badge');
    expect(overdueBadge).toHaveTextContent('逾期 1 项');

    fireEvent.click(screen.getByTestId('milestone-summary-copy-md-btn'));
    expect(screen.getByTestId('milestone-summary-copy-md-btn')).toHaveTextContent(/已复制|复制进度/);

    // L2 preset click
    fireEvent.click(screen.getByTestId('sidebar-overview-preset-0'));
    expect(onChange).toHaveBeenCalledWith(
      'p-1',
      'description',
      '学术论文撰述、定量对比实验与可复现消融分析',
    );
    fireEvent.click(screen.getByTestId('sidebar-overview-copy-md'));

    // L4 sidebar materials search & copy
    fireEvent.click(screen.getByTestId('sidebar-materials-copy-md'));
    fireEvent.change(screen.getByTestId('sidebar-materials-search-input'), {
      target: { value: 'Transformer' },
    });
    expect(screen.getByText(/Transformer 消融实验核心超参表/)).toBeInTheDocument();
    expect(screen.queryByText(/无关基线日志记录/)).not.toBeInTheDocument();
  });
});
