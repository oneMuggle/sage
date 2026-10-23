/**
 * A4 — LaneDetailDrawer: delivery package rendering, acceptance checks,
 * and the accept/reject decision zone wired to laneBoardStore.decide().
 *
 * Mocks at the desktopInvoke seam (same pattern as Orchestration.test.tsx),
 * exercising the real orchestrationClient + store flow.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: vi.fn(),
}));

import { useLaneBoardStore } from '../../../entities/orchestration/laneBoardStore';
import { invoke } from '../../../shared/api/desktopInvoke';
import type { Lane, LaneEvent } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { LaneDetailDrawer } from '../LaneDetailDrawer';

const invokeMock = invoke as unknown as ReturnType<typeof vi.fn>;

function makeLane(overrides: Partial<Lane> = {}): Lane {
  return {
    lane_id: 'lane-1',
    task_id: 'task-1',
    agent_id: 'coder',
    status: 'succeeded',
    created_at: 0,
    started_at: null,
    completed_at: null,
    worktree: '/repo/.worktrees/lane-1',
    heartbeat: null,
    error: null,
    permission_preset: 'implement',
    metadata: { acceptance_pending: true },
    ...overrides,
  };
}

function makeAcceptanceEvent(checks: unknown[]): LaneEvent {
  return {
    event_id: 'evt-1',
    event_type: 'lane.acceptance.completed',
    lane_id: 'lane-1',
    task_id: 'task-1',
    agent_id: 'coder',
    timestamp: 1759000000000,
    provenance: 'LiveLane',
    metadata: { checks, all_passed: true },
  };
}

/** Live harness: lane prop tracks the store like LaneBoard does. */
function LiveDrawer() {
  const lane = useLaneBoardStore((s) => s.lanes.find((l) => l.lane_id === 'lane-1') ?? null);
  return (
    <I18nProvider>
      <LaneDetailDrawer lane={lane} open onClose={() => {}} />
    </I18nProvider>
  );
}

describe('LaneDetailDrawer (A4)', () => {
  beforeEach(() => {
    invokeMock.mockReset();
    useLaneBoardStore.setState({ lanes: [], loading: false, error: null, teamIdFilter: null });
    invokeMock.mockImplementation(async () => []);
  });

  it('renders the delivery package: pending state, worktree path, decision zone', () => {
    render(
      <I18nProvider>
        <LaneDetailDrawer lane={makeLane()} open onClose={() => {}} />
      </I18nProvider>,
    );

    expect(screen.getByTestId('lane-detail-drawer')).toBeTruthy();
    expect(screen.getByTestId('acceptance-state')).toBeTruthy();
    expect(screen.getByText('/repo/.worktrees/lane-1')).toBeTruthy();
    expect(screen.getByTestId('decision-zone')).toBeTruthy();
    expect(screen.getByTestId('decision-accept')).toBeTruthy();
    expect(screen.getByTestId('decision-reject')).toBeTruthy();
  });

  it('renders acceptance checks from the lane.acceptance.completed event', async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'orchestration_list_lane_events') {
        return [
          makeAcceptanceEvent([
            { name: 'pytest', passed: true, summary: '3 passed', skipped: false },
            { name: 'ruff', passed: false, summary: 'F401 unused', skipped: false },
          ]),
        ];
      }
      return [];
    });
    render(
      <I18nProvider>
        <LaneDetailDrawer lane={makeLane()} open onClose={() => {}} />
      </I18nProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('acceptance-checks')).toBeTruthy());
    expect(screen.getByText('pytest')).toBeTruthy();
    expect(screen.getByText('ruff')).toBeTruthy();
    expect(screen.getByText('3 passed')).toBeTruthy();
  });

  it('events failure degrades the checks section without blocking decisions', async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'orchestration_list_lane_events') {
        throw new Error('events down');
      }
      return [];
    });
    render(
      <I18nProvider>
        <LaneDetailDrawer lane={makeLane()} open onClose={() => {}} />
      </I18nProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('acceptance-checks-empty')).toBeTruthy());
    expect(screen.getByTestId('decision-zone')).toBeTruthy();
  });

  it('accept flow: invokes the decision channel and hides the zone once decided', async () => {
    const decided = makeLane({
      metadata: {
        acceptance_pending: false,
        accepted_at: 1759000001000,
        merge: { code: 'merged', branch: 'lane/accept/lane-1-ab12cd34' },
      },
    });
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'orchestration_lane_decision') {
        return {
          ok: true,
          lane: decided,
          decision: 'accept',
          merged: true,
          already: false,
          warning: null,
          merge: { code: 'merged' },
        };
      }
      return [];
    });
    useLaneBoardStore.setState({ lanes: [makeLane()], error: null });
    render(<LiveDrawer />);

    fireEvent.change(screen.getByTestId('decision-reason'), { target: { value: 'lgtm' } });
    fireEvent.click(screen.getByTestId('decision-accept'));

    await waitFor(() => expect(screen.queryByTestId('decision-zone')).toBeNull());
    expect(invokeMock).toHaveBeenCalledWith('orchestration_lane_decision', {
      lane_id: 'lane-1',
      decision: 'accept',
      reason: 'lgtm',
    });
    expect(screen.getByTestId('merge-info')).toBeTruthy();
  });

  it('reject flow: invokes with the reject decision', async () => {
    const rejected = makeLane({
      metadata: { acceptance_pending: false, rejected_at: 1759000001000 },
    });
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'orchestration_lane_decision') {
        return {
          ok: true,
          lane: rejected,
          decision: 'reject',
          merged: false,
          already: false,
          warning: null,
          merge: null,
        };
      }
      return [];
    });
    useLaneBoardStore.setState({ lanes: [makeLane()], error: null });
    render(<LiveDrawer />);

    fireEvent.click(screen.getByTestId('decision-reject'));

    await waitFor(() => expect(screen.queryByTestId('decision-zone')).toBeNull());
    expect(invokeMock).toHaveBeenCalledWith('orchestration_lane_decision', {
      lane_id: 'lane-1',
      decision: 'reject',
      reason: '',
    });
  });

  it('decision failure shows an inline error and keeps the zone', async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'orchestration_lane_decision') {
        throw new Error('main repo dirty');
      }
      return [];
    });
    useLaneBoardStore.setState({ lanes: [makeLane()], error: null });
    render(<LiveDrawer />);

    fireEvent.click(screen.getByTestId('decision-accept'));

    await waitFor(() => expect(screen.getByTestId('decision-error')).toBeTruthy());
    expect(screen.getByText('main repo dirty')).toBeTruthy();
    expect(screen.getByTestId('decision-zone')).toBeTruthy();
  });

  it('already-decided lanes render no decision zone', () => {
    const lane = makeLane({ metadata: { accepted_at: 1759000001000 } });
    render(
      <I18nProvider>
        <LaneDetailDrawer lane={lane} open onClose={() => {}} />
      </I18nProvider>,
    );

    expect(screen.queryByTestId('decision-zone')).toBeNull();
  });

  it('non-succeeded lanes render no decision zone', () => {
    render(
      <I18nProvider>
        <LaneDetailDrawer lane={makeLane({ status: 'running' })} open onClose={() => {}} />
      </I18nProvider>,
    );

    expect(screen.queryByTestId('decision-zone')).toBeNull();
  });

  it('closed drawer renders nothing', () => {
    render(
      <I18nProvider>
        <LaneDetailDrawer lane={makeLane()} open={false} onClose={() => {}} />
      </I18nProvider>,
    );

    expect(screen.queryByTestId('lane-detail-drawer')).toBeNull();
  });

  it('renders the review verdict with assertion count', () => {
    render(
      <I18nProvider>
        <LaneDetailDrawer
          lane={makeLane({ metadata: { review_verdict: 'pass', review_assertion_count: 3 } })}
          open
          onClose={() => {}}
        />
      </I18nProvider>,
    );

    const verdict = screen.getByTestId('review-verdict');
    expect(verdict.textContent).toContain('3');
  });

  it('renders review concerns without a count when absent', () => {
    render(
      <I18nProvider>
        <LaneDetailDrawer
          lane={makeLane({ metadata: { review_verdict: 'fail' } })}
          open
          onClose={() => {}}
        />
      </I18nProvider>,
    );

    expect(screen.getByTestId('review-verdict')).toBeTruthy();
  });

  it('hides the review section when no verdict was stamped', () => {
    render(
      <I18nProvider>
        <LaneDetailDrawer lane={makeLane()} open onClose={() => {}} />
      </I18nProvider>,
    );

    expect(screen.queryByTestId('review-verdict')).toBeNull();
  });

  it('renders the diff summary from the acceptance event', async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'orchestration_list_lane_events') {
        return [
          makeAcceptanceEvent([
            { name: 'diff', passed: true, summary: 'a.txt | 2 +-', skipped: false },
          ]),
        ];
      }
      return [];
    });
    render(
      <I18nProvider>
        <LaneDetailDrawer lane={makeLane()} open onClose={() => {}} />
      </I18nProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('diff-summary')).toBeTruthy());
    expect(screen.getByText('a.txt | 2 +-')).toBeTruthy();
  });

  it('shows the diff empty state when the acceptance has no diff check', async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'orchestration_list_lane_events') {
        return [makeAcceptanceEvent([])];
      }
      return [];
    });
    render(
      <I18nProvider>
        <LaneDetailDrawer lane={makeLane()} open onClose={() => {}} />
      </I18nProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('diff-empty')).toBeTruthy());
  });
});
