// src/widgets/chat/__tests__/PlanCardList.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

// C5 (2026-08-15): handleResume 只回调 onResume(runId)，不再内部调 resumeRun
//（resume 封装进 useChat.resumeOrchestration，恢复 original_request 逐字）。
vi.mock('../../../shared/api/orchRunClient', () => ({
  orchRunClient: {
    listRuns: vi.fn(),
  },
}));

import { PlanCardList } from '../../../components/PlanCardList';
import { orchRunClient } from '../../../shared/api/orchRunClient';

const listRunsMock = orchRunClient.listRuns as unknown as ReturnType<typeof vi.fn>;

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

  // ===== Wave 3 C5 (2026-08-15): 恢复流 —— onResume(runId) 委托 useChat.resumeOrchestration =====
  it('点击恢复 → onResume(runId)（不再内部调 resumeRun）', async () => {
    const onResume = vi.fn();
    listRunsMock.mockResolvedValue([
      { run_id: 'orch-1', session_id: 's1', status: 'done', created_at: 1 },
    ]);
    render(<PlanCardList onResume={onResume} />);
    fireEvent.click(await screen.findByTestId('plan-resume-orch-1'));
    expect(onResume).toHaveBeenCalledWith('orch-1');
  });
});
