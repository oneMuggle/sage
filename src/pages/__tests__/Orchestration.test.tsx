/**
 * M5 — Orchestration page: goal form → createLane invoke payload,
 * board refresh, error toast, sub-agent badge rendering.
 *
 * Mocks at the desktopInvoke seam so the REAL laneBoardStore flow
 * (createLane → refresh) is exercised.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../shared/api/desktopInvoke', () => ({
  invoke: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { useLaneBoardStore } from '../../entities/orchestration/laneBoardStore';
import { invoke } from '../../shared/api/desktopInvoke';
import type { Lane } from '../../shared/api/types';
import { I18nProvider } from '../../shared/lib/i18n';
import { Orchestration } from '../Orchestration';

const invokeMock = invoke as unknown as ReturnType<typeof vi.fn>;
const toastMock = toast as unknown as {
  success: ReturnType<typeof vi.fn>;
  error: ReturnType<typeof vi.fn>;
};

function makeLane(overrides: Partial<Lane> = {}): Lane {
  return {
    lane_id: 'lane-1',
    task_id: 'task-1',
    agent_id: 'researcher',
    status: 'created',
    created_at: 0,
    started_at: null,
    completed_at: null,
    worktree: null,
    heartbeat: null,
    error: null,
    permission_preset: 'implement',
    metadata: { source: 'planner' },
    ...overrides,
  };
}

function renderPage() {
  return render(
    <I18nProvider>
      <Orchestration />
    </I18nProvider>,
  );
}

describe('Orchestration page', () => {
  beforeEach(() => {
    invokeMock.mockReset();
    toastMock.success.mockReset();
    toastMock.error.mockReset();
    useLaneBoardStore.setState({ lanes: [], loading: false, error: null, teamIdFilter: null });
    // Default: board loads empty.
    invokeMock.mockImplementation(async () => []);
  });

  it('submits the goal via orchestration_create_lane and refreshes the board', async () => {
    const created = makeLane();
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'orchestration_create_lane') {
        return { ok: true, team_id: 'team-1', lanes: [created], tasks: [] };
      }
      return [created];
    });

    renderPage();
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'research X' } });
    fireEvent.click(screen.getByRole('button', { name: /创建编排/ }));

    await waitFor(() => expect(toastMock.success).toHaveBeenCalledTimes(1));

    // Invoke payload: goal only (no agent).
    const createCalls = invokeMock.mock.calls.filter(
      (call: unknown[]) => call[0] === 'orchestration_create_lane',
    );
    expect(createCalls).toHaveLength(1);
    expect(createCalls[0]?.[1]).toEqual({ goal: 'research X' });

    // Refresh: initial load + post-create refresh → ≥2 list calls.
    const listCalls = invokeMock.mock.calls.filter(
      (call: unknown[]) => call[0] === 'orchestration_list_lanes',
    );
    expect(listCalls.length).toBeGreaterThanOrEqual(2);

    // Success toast carries the lane count; input cleared.
    expect(String(toastMock.success.mock.calls[0]?.[0])).toContain('1');
    expect((screen.getByRole('textbox') as HTMLInputElement).value).toBe('');
  });

  it('shows an error toast when creation fails', async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === 'orchestration_create_lane') {
        throw new Error('Backend POST → 400: goal must not be empty');
      }
      return [];
    });

    renderPage();
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'bad goal' } });
    fireEvent.click(screen.getByRole('button', { name: /创建编排/ }));

    await waitFor(() => expect(toastMock.error).toHaveBeenCalledTimes(1));
    const message = String(toastMock.error.mock.calls[0]?.[0]);
    expect(message).toContain('创建编排失败');
    expect(message).toContain('400');
  });

  it('keeps the create button disabled while the goal is empty', () => {
    renderPage();
    const button = screen.getByRole('button', { name: /创建编排/ }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    const createCalls = invokeMock.mock.calls.filter(
      (call: unknown[]) => call[0] === 'orchestration_create_lane',
    );
    expect(createCalls).toHaveLength(0);
  });

  it('renders a distinguishing badge for sub-agent lanes', async () => {
    invokeMock.mockImplementation(async () => [
      makeLane({ lane_id: 'lane-sub', metadata: { source: 'subagent' }, status: 'running' }),
      makeLane({ lane_id: 'lane-plain', metadata: {} }),
    ]);

    renderPage();

    const badges = await screen.findAllByTestId('lane-source-badge');
    expect(badges).toHaveLength(1);
    expect(badges[0]?.textContent).toBe('子代理');
  });
});
