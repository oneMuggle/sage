// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ProjectHealthSummary, ProjectsHealthCheckResult } from '../../../shared/api';
import { HealthDashboard } from '../HealthDashboard';

const listMock = vi.fn();

vi.mock('../../../shared/api', () => ({
  projectApi: {
    listProjectsHealth: (...args: unknown[]) => listMock(...args),
  },
}));

function summary(
  project_id: string,
  severity: ProjectHealthSummary['severity'],
  overdueCount = 0,
): ProjectHealthSummary {
  return {
    project_id,
    project_name: `项目 ${project_id}`,
    severity,
    project_stage: '实施',
    total_milestones: 3,
    completed_milestones: 1,
    in_progress_milestones: 1,
    pending_milestones: 1,
    blocked_milestones: 0,
    overdue: Array.from({ length: overdueCount }, (_, index) => ({
      milestone_id: `m-${project_id}-${index}`,
      title: '中期检查',
      due_date: '2026-11-01',
      days_overdue: 13,
      status: 'pending',
    })),
  };
}

function result(): ProjectsHealthCheckResult {
  return {
    checked: 3,
    severities: { critical: 1, warning: 1, ok: 1 },
    summaries: [
      summary('p1', 'critical', 2),
      summary('p2', 'warning'),
      summary('p3', 'ok'),
    ],
  };
}

describe('HealthDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders severity counts and every project row', async () => {
    listMock.mockResolvedValue(result());
    render(<HealthDashboard />);

    await waitFor(() => expect(screen.getByTestId('health-dashboard-list')).toBeTruthy());
    expect(listMock).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('project-health-dashboard').textContent).toContain('风险 1');
    expect(screen.getByTestId('health-dashboard-row-p1')).toBeTruthy();
    expect(screen.getByTestId('health-dashboard-row-p2')).toBeTruthy();
    expect(screen.getByTestId('health-dashboard-row-p3')).toBeTruthy();
    expect(screen.getByTestId('health-dashboard-row-p1').textContent).toContain('逾期 2 项');
  });

  it('filters rows by severity', async () => {
    listMock.mockResolvedValue(result());
    render(<HealthDashboard />);
    await waitFor(() => expect(screen.getByTestId('health-dashboard-list')).toBeTruthy());

    fireEvent.click(screen.getByTestId('health-dashboard-filter-critical'));

    expect(screen.getByTestId('health-dashboard-row-p1')).toBeTruthy();
    expect(screen.queryByTestId('health-dashboard-row-p2')).toBeNull();
    expect(screen.queryByTestId('health-dashboard-row-p3')).toBeNull();
  });

  it('shows an empty hint when nothing matches the filter', async () => {
    listMock.mockResolvedValue({
      checked: 1,
      severities: { critical: 0, warning: 0, ok: 1 },
      summaries: [summary('p1', 'ok')],
    });
    render(<HealthDashboard />);
    await waitFor(() => expect(screen.getByTestId('health-dashboard-row-p1')).toBeTruthy());

    fireEvent.click(screen.getByTestId('health-dashboard-filter-critical'));

    expect(screen.getByTestId('health-dashboard-none')).toBeTruthy();
  });

  it('shows the empty state when there are no active projects', async () => {
    listMock.mockResolvedValue({
      checked: 0,
      severities: { critical: 0, warning: 0, ok: 0 },
      summaries: [],
    });
    render(<HealthDashboard />);

    await waitFor(() => expect(screen.getByTestId('health-dashboard-empty')).toBeTruthy());
  });

  it('surfaces API failures', async () => {
    listMock.mockRejectedValue(new Error('后端不可用'));
    render(<HealthDashboard />);

    await waitFor(() =>
      expect(screen.getByTestId('health-dashboard-error').textContent).toContain('后端不可用'),
    );
  });

  it('re-checks when the refresh button is pressed', async () => {
    listMock.mockResolvedValue(result());
    render(<HealthDashboard />);
    await waitFor(() => expect(screen.getByTestId('health-dashboard-list')).toBeTruthy());

    listMock.mockResolvedValue({
      checked: 1,
      severities: { critical: 0, warning: 0, ok: 1 },
      summaries: [summary('p9', 'ok')],
    });
    fireEvent.click(screen.getByTestId('health-dashboard-refresh'));

    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId('health-dashboard-row-p9')).toBeTruthy();
  });
});
