/**
 * ConstraintSummaryWidget 组件测试 (2026-09-25)
 *
 * 项目类型分类系统 - Phase 4.6
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { projectApi } from '../../shared/api';

import { ConstraintEditor } from './ConstraintEditor';
import { ConstraintManager } from './ConstraintManager';
import { ConstraintSummaryWidget } from './ConstraintSummaryWidget';
import { GitStatusWidget } from './GitStatusWidget';
import { ProjectAdvisorCard } from './ProjectAdvisorCard';

// Mock projectApi
vi.mock('../../shared/api', () => ({
  projectApi: {
    listConstraints: vi.fn(),
    createConstraint: vi.fn().mockResolvedValue({}),
    updateConstraint: vi.fn().mockResolvedValue({}),
    addMaterialFromFile: vi.fn().mockResolvedValue({}),
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
        createdAt: 1000,
        updatedAt: 1000,
      },
    ]);

    render(<ConstraintSummaryWidget projectId="test-project" projectType="coding" />);

    await waitFor(() => {
      expect(screen.getByText('code-style')).toBeInTheDocument();
      expect(screen.getByText('git-commit')).toBeInTheDocument();
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

    expect(screen.getByTestId('constraint-summary-high-priority-count')).toHaveTextContent('高优 ≥P8：1 条');
    const previewToggle = screen.getByTestId('constraint-summary-preview-toggle');
    fireEvent.click(previewToggle);
    expect(screen.getByTestId('constraint-summary-preview-list')).toHaveTextContent(
      '严禁将明文密钥提交至版本库',
    );
    fireEvent.click(screen.getByTestId('constraint-summary-quick-toggle-c-p30-1'));
    await waitFor(() => {
      expect(projectApi.updateConstraint).toHaveBeenCalledWith('test-project', 'c-p30-1', {
        enabled: false,
      });
    });

    // Expand ProjectAdvisorCard details and convert risk #0 to AI constraint
    const toggleDetails = await screen.findByTestId('advisor-toggle-details-btn');
    fireEvent.click(toggleDetails);
    const guardBtn = screen.getByTestId('advisor-risk-to-constraint-0');
    fireEvent.click(guardBtn);
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
    fireEvent.click(screen.getByTestId('git-widget-copy-sha-abc1234567'));

    fireEvent.click(screen.getByTestId('constraint-priority-preset-10'));
    expect(screen.getByDisplayValue('10')).toBeInTheDocument();
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
  });
});
