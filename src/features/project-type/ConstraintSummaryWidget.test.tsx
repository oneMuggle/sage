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
});
