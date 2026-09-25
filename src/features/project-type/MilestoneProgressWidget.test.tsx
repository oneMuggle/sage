/**
 * MilestoneProgressWidget 组件测试 (2026-09-25)
 *
 * 项目类型分类系统 - Phase 4.6
 */

import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { projectApi } from '../../shared/api';

import { MilestoneProgressWidget } from './MilestoneProgressWidget';

// Mock projectApi
vi.mock('../../shared/api', () => ({
  projectApi: {
    listMilestones: vi.fn(),
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
});
