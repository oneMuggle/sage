// src/widgets/chat/__tests__/PlanCardList.test.tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/api/orchRunClient', () => ({
  orchRunClient: {
    listRuns: vi.fn(),
    resumeRun: vi.fn(),
  },
}));

import { PlanCardList } from '../../../components/PlanCardList';
import { orchRunClient } from '../../../shared/api/orchRunClient';

const listRunsMock = orchRunClient.listRuns as unknown as ReturnType<typeof vi.fn>;
const resumeRunMock = orchRunClient.resumeRun as unknown as ReturnType<typeof vi.fn>;

describe('PlanCardList (P1-5)', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders empty state when no runs', async () => {
    listRunsMock.mockResolvedValue([]);
    render(<PlanCardList onResume={() => {}} />);
    expect(await screen.findByText('暂无历史')).toBeInTheDocument();
  });

  it('renders history rows from listRuns', async () => {
    listRunsMock.mockResolvedValue([
      { run_id: 'orch-1', session_id: 's1', status: 'running', created_at: 1755200000000 },
      { run_id: 'orch-2', session_id: 's2', status: 'done', created_at: 1755100000000 },
    ]);
    render(<PlanCardList onResume={() => {}} />);
    expect(await screen.findByTestId('plan-history-row-orch-1')).toBeInTheDocument();
    expect(screen.getByTestId('plan-history-row-orch-2')).toBeInTheDocument();
    expect(screen.getByText('orch-1')).toBeInTheDocument();
    expect(screen.getByText(/running/)).toBeInTheDocument();
  });

  it('resume button calls onResume with new run + plan', async () => {
    const onResume = vi.fn();
    listRunsMock.mockResolvedValue([
      { run_id: 'orch-1', session_id: 's1', status: 'done', created_at: 1 },
    ]);
    resumeRunMock.mockResolvedValue({
      ok: true,
      new_run_id: 'orch-new',
      session_id: 's1',
      plan: [{ task_id: 't1', agent_id: 'primary', goal: 'g' }],
    });
    render(<PlanCardList onResume={onResume} />);
    fireEvent.click(await screen.findByTestId('plan-resume-orch-1'));
    await waitFor(() => {
      expect(onResume).toHaveBeenCalledWith('orch-new', [
        { task_id: 't1', agent_id: 'primary', goal: 'g' },
      ]);
    });
  });
});
