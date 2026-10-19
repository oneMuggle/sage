/**
 * ConstraintSummaryWidget 组件测试 (2026-09-25)
 *
 * 项目类型分类系统 - Phase 4.6
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { projectApi } from '../../shared/api';
import { I18nProvider } from '../../shared/lib/i18n';
import { GitStatusSection } from '../../widgets/sidebar/sections/GitStatusSection';

import { BusinessDocumentStyleBar, CodingHooksGovernanceBar, ResearchCitationAndToneBar } from './BuiltinCheckpointAndStyleBar';
import { ConstraintEditor } from './ConstraintEditor';
import { ConstraintManager } from './ConstraintManager';
import { ConstraintSummaryWidget } from './ConstraintSummaryWidget';
import { GitStatusWidget } from './GitStatusWidget';
import { ProjectAdvisorCard } from './ProjectAdvisorCard';

// Mock projectApi
vi.mock('../../shared/api', () => ({
  projectApi: {
    list: vi.fn().mockResolvedValue([{ id: 'proj-sider-1', path: '/workspace/proj-sider-1', name: 'sider', lastOpenedAt: 100 }]),
    listConstraints: vi.fn(),
    createConstraint: vi.fn().mockResolvedValue({}),
    createMilestone: vi.fn().mockResolvedValue({}),
    updateConstraint: vi.fn().mockResolvedValue({}),
    addMaterial: vi.fn().mockResolvedValue({}),
    addMaterialFromFile: vi.fn().mockResolvedValue({}),
    confirmKnowledge: vi.fn().mockResolvedValue({}),
    getAdvice: vi.fn().mockResolvedValue({
      healthScore: 86,
      summary: '项目约束与阶段运转健康',
      risks: [{ severity: 'medium', description: '部分文书未留存快照', suggestion: '创建归档快照' }],
      suggestions: [{ priority: 'high', action: '补齐法务复核', reason: '提升合规完备度' }],
      cachedAt: 1700000000,
    }),
  },
}));

vi.mock('../../shared/api/desktopInvoke', () => ({
  invoke: vi.fn().mockResolvedValue({
    is_repo: true,
    current_branch: 'main',
    modified_files: ['src/App.tsx'],
    staged_files: ['README.md'],
    untracked_files: [],
    recent_commits: [{ sha: 'abc1234567', author: 'dev', date: '2026-10-13 10:00:00', message: 'feat: init' }],
  }),
}));

vi.mock('../../shared/api/projectApi', () => ({
  projectApi: {
    list: vi.fn().mockResolvedValue([
      { id: 'proj-sider-1', path: '/workspace/proj-sider-1', name: 'sider', lastOpenedAt: 100 },
    ]),
    addMaterial: vi.fn().mockResolvedValue({}),
    addMaterialFromFile: vi.fn().mockResolvedValue({}),
    confirmKnowledge: vi.fn().mockResolvedValue({}),
  },
}));

vi.mock('../../shared/api/gitStatusApi', () => ({
  getGitStatus: vi.fn().mockResolvedValue({
    is_git_repo: true,
    branch: 'main',
    files: [
      { path: 'src/index.ts', status: 'modified' },
      { path: 'README.md', status: 'staged' },
    ],
  }),
}));

const mockListConstraints = vi.mocked(projectApi.listConstraints);

describe('ConstraintSummaryWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows loading state initially', () => {
    mockListConstraints.mockImplementation(
      () => new Promise(() => {}), // Never resolves
    );

    render(<ConstraintSummaryWidget projectId="test-project" projectType="coding" />);
    expect(screen.getByText('加载中...')).toBeInTheDocument();
  });

  it('renders constraint summary with enabled count', async () => {
    mockListConstraints.mockResolvedValue([
      {
        id: 'c1',
        projectId: 'test-project',
        category: 'code-style',
        content: 'Use TypeScript',
        priority: 5,
        enabled: true,
        createdAt: 1000,
        updatedAt: 1000,
      },
      {
        id: 'c2',
        projectId: 'test-project',
        category: 'git-commit',
        content: 'Conventional commits',
        priority: 3,
        enabled: false,
        createdAt: 1000,
        updatedAt: 1000,
      },
    ]);

    render(<ConstraintSummaryWidget projectId="test-project" projectType="coding" />);

    await waitFor(() => {
      expect(screen.getByText('1 / 2')).toBeInTheDocument();
    });
  });

  it('shows category breakdown when constraints exist', async () => {
    mockListConstraints.mockResolvedValue([
      {
        id: 'c1',
        projectId: 'test-project',
        category: 'code-style',
        content: 'Rule 1',
        priority: 5,
        enabled: true,
        createdAt: 1000,
        updatedAt: 1000,
      },
      {
        id: 'c2',
        projectId: 'test-project',
        category: 'code-style',
        content: 'Rule 2',
        priority: 3,
        enabled: true,
        createdAt: 1000,
        updatedAt: 1000,
      },
      {
        id: 'c3',
        projectId: 'test-project',
        category: 'git-commit',
        content: 'Rule 3',
        priority: 4,
        enabled: true,
        triggerPattern: 'src/**/*.ts',
        createdAt: 1000,
        updatedAt: 1000,
      },
    ]);

    render(<ConstraintSummaryWidget projectId="test-project" projectType="coding" />);

    await waitFor(() => {
      expect(screen.getByText('code-style')).toBeInTheDocument();
      expect(screen.getByText('git-commit')).toBeInTheDocument();
      fireEvent.click(screen.getByTestId('constraint-summary-cats-to-l3-btn'));
      expect(screen.getByTestId('constraint-summary-cats-to-l3-btn')).toHaveTextContent('已存分布L3');
      fireEvent.click(screen.getByTestId('constraint-summary-cats-to-l4-btn'));
      expect(screen.getByTestId('constraint-summary-cats-to-l4-btn')).toHaveTextContent('已存分布L4');
      fireEvent.click(screen.getByTestId('constraint-summary-glob-to-l4-btn'));
      expect(screen.getByTestId('constraint-summary-glob-to-l4-btn')).toHaveTextContent('已存Glob至L4');
    });
  });

  it('shows hint when no constraints exist', async () => {
    mockListConstraints.mockResolvedValue([]);

    render(<ConstraintSummaryWidget projectId="test-project" projectType="coding" />);

    await waitFor(() => {
      expect(screen.getByText(/暂无约束/)).toBeInTheDocument();
      expect(screen.getByText(/可导入代码风格/)).toBeInTheDocument();
    });
  });

  it('shows different hint for research project type', async () => {
    mockListConstraints.mockResolvedValue([]);

    render(<ConstraintSummaryWidget projectId="test-project" projectType="research" />);

    await waitFor(() => {
      expect(screen.getByText(/可导入学术写作/)).toBeInTheDocument();
    });
  });

  it('shows error message on API failure', async () => {
    mockListConstraints.mockRejectedValue(new Error('Network error'));

    render(<ConstraintSummaryWidget projectId="test-project" projectType="coding" />);

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });
  });

  it('renders ConstraintEditor archetype rule content presets and always glob button (Phase P26)', async () => {
    const onSave = vi.fn();
    render(
      <ConstraintEditor
        open={true}
        onOpenChange={vi.fn()}
        projectId="test-project"
        projectType="business"
        constraint={null}
        onSave={onSave}
      />,
    );

    expect(screen.getByTestId('constraint-editor-content-presets')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('constraint-content-preset-0'));
    fireEvent.click(screen.getByTestId('constraint-glob-always-btn'));
    fireEvent.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(projectApi.createConstraint).toHaveBeenCalledWith(
        'test-project',
        expect.objectContaining({
          category: 'compliance',
          triggerPattern: 'always',
          priority: 9,
        }),
      );
    });
  });

  it('renders GitStatusWidget markdown copy button (Phase P26)', async () => {
    render(<GitStatusWidget projectId="test-project" />);
    const copyBtn = await screen.findByTestId('git-status-copy-md-btn');
    fireEvent.click(copyBtn);
    await waitFor(() => {
      expect(screen.getByTestId('git-status-copy-md-btn')).toHaveTextContent(/已复制|复制报告/);
    });
  });

  it('supports ConstraintManager sample glob pills, clear button, keyword search, and ProjectAdvisorCard markdown copy (Phase P27)', async () => {
    mockListConstraints.mockResolvedValue([
      {
        id: 'c-glob-1',
        projectId: 'test-project',
        category: 'document_format',
        content: '严格遵循 GB/T 9704 公文格式',
        triggerPattern: '02_审校与修订过程/**',
        priority: 8,
        enabled: true,
        createdAt: 1000,
        updatedAt: 1000,
      },
    ]);

    render(
      <>
        <ConstraintManager projectId="test-project" projectType="business" />
        <ProjectAdvisorCard projectId="test-project" />
      </>,
    );

    const sampleBtn = await screen.findByTestId('constraint-glob-sample-1');
    fireEvent.click(sampleBtn);
    await waitFor(() => {
      expect(screen.getByTestId('constraint-glob-match-count')).toHaveTextContent('命中 1 条生效约束');
    });

    fireEvent.click(screen.getByTestId('constraint-glob-clear-btn'));
    expect(screen.getByTestId('constraint-glob-test-input')).toHaveValue('');

    fireEvent.change(screen.getByTestId('constraint-search-input'), {
      target: { value: 'GB/T 9704' },
    });
    expect(screen.getByText('严格遵循 GB/T 9704 公文格式')).toBeInTheDocument();

    const copyAdvisorBtn = await screen.findByTestId('advisor-copy-md-btn');
    fireEvent.click(copyAdvisorBtn);
    expect(screen.getByTestId('advisor-copy-md-btn')).toHaveTextContent(/已复制|复制诊断/);
  });

  it('supports ConstraintSummaryWidget top-priority preview toggle, active rules Markdown export, and ProjectAdvisorCard M3 Risk -> Constraint closed loop (Phase P30)', async () => {
    mockListConstraints.mockResolvedValue([
      {
        id: 'c-p30-1',
        projectId: 'test-project',
        category: 'security',
        content: '严禁将明文密钥提交至版本库',
        triggerPattern: 'src/**',
        priority: 9,
        enabled: true,
        createdAt: 1000,
        updatedAt: 1000,
      },
      {
        id: 'c-p39-disabled',
        projectId: 'test-project',
        category: 'testing',
        content: '禁用待恢复规则',
        triggerPattern: 'tests/**',
        priority: 6,
        enabled: false,
        createdAt: 1000,
        updatedAt: 1000,
      },
    ]);

    render(
      <>
        <ConstraintSummaryWidget projectId="test-project" projectType="coding" />
        <ProjectAdvisorCard projectId="test-project" />
      </>,
    );

    const copyRulesBtn = await screen.findByTestId('constraint-summary-copy-md-btn');
    fireEvent.click(copyRulesBtn);
    expect(screen.getByTestId('constraint-summary-copy-md-btn')).toHaveTextContent(/已复制|复制规则/);
    fireEvent.click(screen.getByTestId('constraint-summary-save-l3-btn'));
    expect(screen.getByTestId('constraint-summary-save-l3-btn')).toHaveTextContent('已存高优 L3');
    fireEvent.click(screen.getByTestId('constraint-summary-save-l4-btn'));
    expect(screen.getByTestId('constraint-summary-save-l4-btn')).toHaveTextContent('已存 L4');
    fireEvent.click(screen.getByTestId('constraint-summary-top-to-milestone-btn'));
    expect(screen.getByTestId('constraint-summary-top-to-milestone-btn')).toHaveTextContent('已转里程碑');

    expect(screen.getByTestId('constraint-summary-high-priority-count')).toHaveTextContent('高优 ≥P8：1 条');
    fireEvent.click(screen.getByTestId('constraint-summary-glob-to-l3-btn'));
    expect(screen.getByTestId('constraint-summary-glob-to-l3-btn')).toHaveTextContent('已存Glob至L3');
    fireEvent.click(screen.getByTestId('constraint-summary-copy-glob-btn'));
    fireEvent.click(screen.getByTestId('constraint-summary-disabled-to-milestone-btn'));
    expect(screen.getByTestId('constraint-summary-disabled-to-milestone-btn')).toHaveTextContent('已建复核里程碑');
    fireEvent.click(screen.getByTestId('constraint-summary-copy-cats-btn'));
    expect(screen.getByTestId('constraint-summary-copy-cats-btn')).toHaveTextContent(/已复制分布|复制分布/);
    fireEvent.click(screen.getByTestId('constraint-summary-enable-all-btn'));
    await waitFor(() => {
      expect(projectApi.updateConstraint).toHaveBeenCalledWith('test-project', 'c-p39-disabled', {
        enabled: true,
      });
    });
    fireEvent.click(screen.getByTestId('constraint-summary-cat-pill-security'));
    fireEvent.click(screen.getByTestId('constraint-summary-clear-cat'));
    expect(screen.getByTestId('constraint-summary-preview-list')).toHaveTextContent(
      '严禁将明文密钥提交至版本库',
    );
    fireEvent.click(screen.getByTestId('constraint-summary-rule-to-l3-c-p30-1'));
    expect(screen.getByTestId('constraint-summary-rule-to-l3-c-p30-1')).toHaveTextContent('已存 L3');
    fireEvent.click(screen.getByTestId('constraint-summary-rule-to-milestone-c-p30-1'));
    expect(screen.getByTestId('constraint-summary-rule-to-milestone-c-p30-1')).toHaveTextContent('已转里程碑');
    fireEvent.click(screen.getByTestId('constraint-summary-rule-to-l4-c-p30-1'));
    expect(screen.getByTestId('constraint-summary-rule-to-l4-c-p30-1')).toHaveTextContent('已存L4');
    fireEvent.click(screen.getByTestId('constraint-summary-rule-copy-c-p30-1'));
    fireEvent.click(screen.getByTestId('constraint-summary-quick-toggle-c-p30-1'));
    await waitFor(() => {
      expect(projectApi.updateConstraint).toHaveBeenCalledWith('test-project', 'c-p30-1', {
        enabled: false,
      });
    });

    // Expand ProjectAdvisorCard details and convert risk #0 to AI constraint
    fireEvent.click(await screen.findByTestId('advisor-save-l3-btn'));
    expect(screen.getByTestId('advisor-save-l3-btn')).toHaveTextContent('已沉淀 L3');
    fireEvent.click(await screen.findByTestId('advisor-save-l4-btn'));
    expect(screen.getByTestId('advisor-save-l4-btn')).toHaveTextContent('已存 L4');
    const toggleDetails = await screen.findByTestId('advisor-toggle-details-btn');
    fireEvent.click(toggleDetails);
    fireEvent.click(screen.getByTestId('advisor-risk-to-milestone-0'));
    expect(screen.getByTestId('advisor-risk-to-milestone-0')).toHaveTextContent('已建里程碑');
    fireEvent.click(screen.getByTestId('advisor-suggestion-to-milestone-0'));
    expect(screen.getByTestId('advisor-suggestion-to-milestone-0')).toHaveTextContent('已转里程碑');
    fireEvent.click(screen.getByTestId('advisor-risk-to-l3-0'));
    expect(screen.getByTestId('advisor-risk-to-l3-0')).toHaveTextContent('已存L3');
    fireEvent.click(screen.getByTestId('advisor-risk-to-l4-0'));
    expect(screen.getByTestId('advisor-risk-to-l4-0')).toHaveTextContent('已存L4');
    fireEvent.click(screen.getByTestId('advisor-suggestion-to-l3-0'));
    expect(screen.getByTestId('advisor-suggestion-to-l3-0')).toHaveTextContent('已存L3');
    fireEvent.click(screen.getByTestId('advisor-risk-filter-high'));
    fireEvent.click(screen.getByTestId('advisor-risk-filter-all'));
    fireEvent.click(screen.getByTestId('advisor-batch-risks-to-milestone-btn'));
    expect(screen.getByTestId('advisor-batch-risks-to-milestone-btn')).toHaveTextContent('已全部风险转里程碑');
    fireEvent.click(screen.getByTestId('advisor-batch-risks-to-l3-btn'));
    expect(screen.getByTestId('advisor-batch-risks-to-l3-btn')).toHaveTextContent('已全部风险存 L3');
    fireEvent.click(screen.getByTestId('advisor-batch-suggestions-to-l3-btn'));
    expect(screen.getByTestId('advisor-batch-suggestions-to-l3-btn')).toHaveTextContent('已全部建议存 L3');
    fireEvent.click(screen.getByTestId('advisor-guard-all-risks-btn'));
    await waitFor(() => {
      expect(projectApi.createConstraint).toHaveBeenCalledWith(
        'test-project',
        expect.objectContaining({
          category: 'risk_guard',
          content: '部分文书未留存快照 — 防护规范：创建归档快照',
          priority: 7,
        }),
      );
      expect(screen.getByTestId('advisor-risk-to-constraint-0')).toHaveTextContent('已固化约束');
    });
  });

  it('supports GitStatusWidget category filter pills & L4 ingest, and ConstraintEditor priority tier presets (Phase P32)', async () => {
    render(
      <>
        <GitStatusWidget projectId="test-project" />
        <ConstraintEditor
          open={true}
          onOpenChange={vi.fn()}
          projectId="test-project"
          projectType="coding"
          constraint={null}
          onSave={vi.fn()}
        />
      </>,
    );

    const toggleFilesBtn = await screen.findByTestId('git-status-files-toggle');
    fireEvent.click(toggleFilesBtn);
    expect(screen.getByText('[S] README.md')).toBeInTheDocument();
    expect(screen.getByText('[M] src/App.tsx')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('git-widget-filter-staged'));
    expect(screen.getByText('[S] README.md')).toBeInTheDocument();
    expect(screen.queryByText('[M] src/App.tsx')).toBeNull();

    fireEvent.click(screen.getByTestId('git-widget-ingest-README.md'));
    await waitFor(() => {
      expect(projectApi.addMaterialFromFile).toHaveBeenCalledWith('test-project', 'README.md');
      expect(screen.getByTestId('git-widget-ingest-README.md')).toHaveTextContent('已纳入 L4');
    });

    fireEvent.click(screen.getByTestId('git-widget-filter-all'));
    fireEvent.click(screen.getByTestId('git-widget-ingest-all-btn'));
    await waitFor(() => {
      expect(projectApi.addMaterialFromFile).toHaveBeenCalledWith('test-project', 'src/App.tsx');
    });
    fireEvent.click(screen.getByTestId('git-widget-guard-README.md'));
    expect(screen.getByTestId('git-widget-guard-README.md')).toHaveTextContent('已护栏');
    fireEvent.click(screen.getByTestId('git-widget-guard-src/App.tsx'));
    expect(screen.getByTestId('git-widget-guard-src/App.tsx')).toHaveTextContent('已护栏');
    fireEvent.click(screen.getByTestId('git-widget-copy-path-README.md'));
    fireEvent.click(screen.getByTestId('git-widget-copy-paths-btn'));
    fireEvent.click(screen.getByTestId('git-widget-files-to-milestone-btn'));
    expect(screen.getByTestId('git-widget-files-to-milestone-btn')).toHaveTextContent('已转里程碑');
    fireEvent.click(screen.getByTestId('git-widget-files-to-l3-btn'));
    expect(screen.getByTestId('git-widget-files-to-l3-btn')).toHaveTextContent('已存变更 L3');
    fireEvent.click(screen.getByTestId('git-widget-copy-branch-btn'));
    fireEvent.click(screen.getByTestId('git-widget-guard-all-btn'));
    fireEvent.click(screen.getByTestId('git-widget-save-commits-l3-btn'));
    expect(screen.getByTestId('git-widget-save-commits-l3-btn')).toHaveTextContent('已沉淀至 L3');
    fireEvent.click(screen.getByTestId('git-widget-save-l4-btn'));
    expect(screen.getByTestId('git-widget-save-l4-btn')).toHaveTextContent('已存提交至 L4');
    fireEvent.click(screen.getByTestId('git-widget-commit-to-milestone-abc1234567'));
    expect(screen.getByTestId('git-widget-commit-to-milestone-abc1234567')).toHaveTextContent('已建里程碑');
    fireEvent.click(screen.getByTestId('git-widget-commit-to-l3-abc1234567'));
    expect(screen.getByTestId('git-widget-commit-to-l3-abc1234567')).toHaveTextContent('已存L3');
    fireEvent.click(screen.getByTestId('git-widget-commit-to-l4-abc1234567'));
    expect(screen.getByTestId('git-widget-commit-to-l4-abc1234567')).toHaveTextContent('已存L4');
    fireEvent.click(screen.getByTestId('git-widget-copy-sha-abc1234567'));

    fireEvent.click(screen.getByTestId('constraint-priority-preset-10'));
    expect(screen.getByDisplayValue('10')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('constraint-pillar-preset-0'));
    fireEvent.click(screen.getByTestId('constraint-pillar-append-0'));
    fireEvent.click(screen.getByTestId('constraint-pillar-fill-all-btn'));
    fireEvent.click(screen.getByTestId('constraint-copy-content-btn'));
    fireEvent.click(screen.getByTestId('constraint-clear-content-btn'));
    fireEvent.click(screen.getByTestId('constraint-pillar-fill-all-btn'));
    fireEvent.click(screen.getByTestId('constraint-dir-glob-0'));
    fireEvent.click(screen.getByTestId('constraint-copy-glob-btn'));

    fireEvent.change(screen.getByTestId('constraint-editor-test-path-input'), {
      target: { value: 'src/index.ts' },
    });
    expect(screen.getByTestId('constraint-editor-test-path-badge')).toHaveTextContent('命中触发');
    fireEvent.click(screen.getByTestId('constraint-editor-copy-md-btn'));
    fireEvent.click(screen.getByTestId('constraint-editor-save-l3-btn'));
    expect(screen.getByTestId('constraint-editor-save-l3-btn')).toHaveTextContent('已沉淀至 L3');
    fireEvent.click(screen.getByTestId('constraint-editor-to-milestone-btn'));
    expect(screen.getByTestId('constraint-editor-to-milestone-btn')).toHaveTextContent('已转里程碑');
    fireEvent.click(screen.getByTestId('constraint-editor-save-l4-btn'));
    expect(screen.getByTestId('constraint-editor-save-l4-btn')).toHaveTextContent('已存 L4');
  });

  it('supports ConstraintManager priority tier filter and Glob matched-only toggle (Phase P33)', async () => {
    mockListConstraints.mockResolvedValue([
      {
        id: 'c-p33-high',
        projectId: 'test-project',
        category: 'security',
        content: '高优禁止明文密钥提交',
        triggerPattern: 'src/**',
        priority: 9,
        enabled: true,
        createdAt: 1000,
        updatedAt: 1000,
      },
      {
        id: 'c-p33-low',
        projectId: 'test-project',
        category: 'style',
        content: '低优代码注释建议',
        triggerPattern: 'docs/**',
        priority: 4,
        enabled: true,
        createdAt: 1000,
        updatedAt: 1000,
      },
    ]);

    render(<ConstraintManager projectId="test-project" projectType="coding" />);

    expect(await screen.findByText('高优禁止明文密钥提交')).toBeInTheDocument();
    expect(screen.getByText('低优代码注释建议')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('constraint-priority-filter-high'));
    expect(screen.getByText('高优禁止明文密钥提交')).toBeInTheDocument();
    expect(screen.queryByText('低优代码注释建议')).toBeNull();

    fireEvent.click(screen.getByTestId('constraint-priority-filter-all'));
    expect(screen.getByText('低优代码注释建议')).toBeInTheDocument();

    fireEvent.change(screen.getByTestId('constraint-glob-test-input'), {
      target: { value: 'src/index.ts' },
    });
    const matchedOnlyBtn = await screen.findByTestId('constraint-glob-matched-only-btn');
    fireEvent.click(matchedOnlyBtn);
    expect(screen.getByText('高优禁止明文密钥提交')).toBeInTheDocument();
    expect(screen.queryByText('低优代码注释建议')).toBeNull();
    fireEvent.click(screen.getByTestId('constraint-batch-promote-l3-btn'));
    expect(screen.getByTestId('constraint-batch-promote-l3-btn')).toHaveTextContent('已批量存 L3');
    fireEvent.click(screen.getByTestId('constraint-batch-save-l4-btn'));
    expect(screen.getByTestId('constraint-batch-save-l4-btn')).toHaveTextContent('已批量存 L4');
    fireEvent.click(screen.getByTestId('constraint-batch-to-milestone-btn'));
    expect(screen.getByTestId('constraint-batch-to-milestone-btn')).toHaveTextContent('已批量转里程碑');
    fireEvent.click(screen.getByTestId('constraint-to-milestone-c-p33-high'));
    expect(screen.getByTestId('constraint-to-milestone-c-p33-high')).toHaveTextContent('已转里程碑');
    fireEvent.click(screen.getByTestId('constraint-to-l4-c-p33-high'));
    expect(screen.getByTestId('constraint-to-l4-c-p33-high')).toHaveTextContent('已存L4');
    fireEvent.click(screen.getByTestId('constraint-promote-profile-c-p33-high'));
    expect(screen.getByTestId('constraint-promote-profile-c-p33-high')).toHaveTextContent('已存L3');
    fireEvent.click(screen.getByTestId('constraint-copy-single-c-p33-high'));

    render(
      <>
        <ResearchCitationAndToneBar projectId="test-project" onApplied={vi.fn()} />
        <BusinessDocumentStyleBar projectId="test-project" onApplied={vi.fn()} />
        <CodingHooksGovernanceBar workspacePath="/tmp/proj" hasHooksConfig={true} hookCount={2} />
      </>,
    );
    fireEvent.click(screen.getByTestId('research-copy-style-md-btn'));
    fireEvent.click(screen.getByTestId('business-copy-style-md-btn'));
    fireEvent.click(screen.getByTestId('coding-hooks-copy-status-md-btn'));

    render(
      <I18nProvider>
        <GitStatusSection collapsed={false} onToggleCollapsed={vi.fn()} />
      </I18nProvider>,
    );
    const saveL4Btn = await screen.findByTestId('git-sider-save-l4-btn');
    fireEvent.click(saveL4Btn);
    expect(screen.getByTestId('git-sider-save-l4-btn')).toHaveTextContent('已存L4');
    fireEvent.click(screen.getByTestId('git-sider-save-l3-btn'));
    expect(screen.getByTestId('git-sider-save-l3-btn')).toHaveTextContent('已存L3');
    fireEvent.click(screen.getByTestId('git-sider-to-milestone-btn'));
    expect(screen.getByTestId('git-sider-to-milestone-btn')).toHaveTextContent('已转里程碑');
    fireEvent.click(screen.getByTestId('git-sider-copy-branch-btn'));
    fireEvent.click(screen.getByTestId('git-sider-guard-all-btn'));
    expect(screen.getByTestId('git-sider-guard-all-btn')).toHaveTextContent('已全护栏');
    fireEvent.click(screen.getByTestId('git-sider-ingest-src/index.ts'));
    expect(screen.getByTestId('git-sider-ingest-src/index.ts')).toHaveTextContent('已存L4');
    fireEvent.click(screen.getByTestId('git-sider-guard-src/index.ts'));
    expect(screen.getByTestId('git-sider-guard-src/index.ts')).toHaveTextContent('已护栏');
    fireEvent.click(screen.getByTestId('git-sider-copy-path-src/index.ts'));
  });
});
