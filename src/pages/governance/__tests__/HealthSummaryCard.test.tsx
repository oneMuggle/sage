import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ProjectHealthSummary } from '../../../shared/api';
import { HealthSummaryCard } from '../sections/HealthSummaryCard';

const checkProjectHealthMock = vi.fn();

vi.mock('../../../shared/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../shared/api')>();
  return {
    ...actual,
    projectApi: {
      ...actual.projectApi,
      checkProjectHealth: (...args: Parameters<typeof actual.projectApi.checkProjectHealth>) =>
        checkProjectHealthMock(...args),
    },
  };
});

function summary(overrides: Partial<ProjectHealthSummary> = {}): ProjectHealthSummary {
  return {
    project_id: 'p-1',
    project_name: 'Alpha',
    severity: 'ok',
    project_stage: 'build',
    total_milestones: 3,
    completed_milestones: 3,
    in_progress_milestones: 0,
    pending_milestones: 0,
    blocked_milestones: 0,
    overdue: [],
    ...overrides,
  };
}

function renderCard() {
  return render(<HealthSummaryCard projectId="p-1" />);
}

describe('HealthSummaryCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows the ok state when nothing is overdue', async () => {
    checkProjectHealthMock.mockResolvedValue(summary());

    renderCard();

    await waitFor(() => {
      expect(screen.getByText('所有里程碑进度正常')).toBeInTheDocument();
    });
    expect(screen.getByTestId('project-health-summary')).toBeInTheDocument();
    expect(screen.getByText('一切正常')).toBeInTheDocument();
  });

  it('lists overdue milestones in the warning state', async () => {
    checkProjectHealthMock.mockResolvedValue(
      summary({
        severity: 'warning',
        completed_milestones: 2,
        in_progress_milestones: 1,
        overdue: [
          {
            milestone_id: 'm-1',
            title: '完成需求评审',
            due_date: '2026-11-12',
            days_overdue: 2,
            status: 'in_progress',
          },
        ],
      }),
    );

    renderCard();

    await waitFor(() => {
      expect(screen.getByText('完成需求评审')).toBeInTheDocument();
    });
    expect(screen.getByText('逾期 2 天')).toBeInTheDocument();
    expect(screen.getByText('需要关注')).toBeInTheDocument();
  });

  it('collapses extra overdue rows and reports the remainder count', async () => {
    checkProjectHealthMock.mockResolvedValue(
      summary({
        severity: 'critical',
        overdue: [1, 2, 3, 4, 5].map((n) => ({
          milestone_id: `m-${n}`,
          title: `里程碑 ${n}`,
          due_date: '2026-11-01',
          days_overdue: 10 + n,
          status: 'pending',
        })),
      }),
    );

    renderCard();

    await waitFor(() => {
      expect(screen.getByText('…还有 2 项')).toBeInTheDocument();
    });
    expect(screen.getByText('存在风险')).toBeInTheDocument();
    expect(screen.queryByText('里程碑 4')).toBeNull();
  });

  it('reports blocked milestones when nothing is overdue', async () => {
    checkProjectHealthMock.mockResolvedValue(
      summary({ severity: 'warning', blocked_milestones: 2, pending_milestones: 1 }),
    );

    renderCard();

    await waitFor(() => {
      expect(screen.getByText('有 2 个里程碑处于阻塞状态')).toBeInTheDocument();
    });
  });

  it('surfaces the error when the health check fails', async () => {
    checkProjectHealthMock.mockRejectedValue(new Error('后端未就绪'));

    renderCard();

    await waitFor(() => {
      expect(screen.getByText('健康检查失败：后端未就绪')).toBeInTheDocument();
    });
    expect(screen.queryByText('所有里程碑进度正常')).toBeNull();
  });

  it('refetches when the project id changes', async () => {
    checkProjectHealthMock.mockResolvedValue(summary());
    const { rerender } = renderCard();
    await waitFor(() => expect(checkProjectHealthMock).toHaveBeenCalledWith('p-1'));

    rerender(<HealthSummaryCard projectId="p-2" />);

    await waitFor(() => expect(checkProjectHealthMock).toHaveBeenCalledWith('p-2'));
    expect(checkProjectHealthMock).toHaveBeenCalledTimes(2);
  });
});
