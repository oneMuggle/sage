/**
 * ConstraintSummaryWidget 组件测试 (2026-09-25)
 *
 * 项目类型分类系统 - Phase 4.6
 */

import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { projectApi } from '../../shared/api';

import { ConstraintSummaryWidget } from './ConstraintSummaryWidget';

// Mock projectApi
vi.mock('../../shared/api', () => ({
  projectApi: {
    listConstraints: vi.fn(),
  },
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
});
