import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

const mockRequestMessageJump = vi.fn();

vi.mock('../../features/chat/messageJumpStore', () => ({
  requestMessageJump: (input: unknown) => mockRequestMessageJump(input),
}));

vi.mock('../../entities/scheduled/taskStore', () => {
  const state = {
    tasks: [
      {
        id: 't-exec',
        name: 'Execute task',
        type: 'recurring',
        schedule: { kind: 'recurring', cron: '0 9 * * *' },
        session_id: 'real-session',
        content: 'run a check',
        enabled: true,
        mode: 'execute',
        last_status: 'succeeded',
        last_result_message_id: 'msg-abc',
        last_duration_ms: 1234,
      },
      {
        id: 't-deliver',
        name: 'Deliver task',
        type: 'once',
        schedule: { kind: 'once', at: Date.now() + 3600_000 },
        session_id: 'real-session',
        content: 'reminder',
        enabled: true,
        mode: 'deliver',
        last_status: 'succeeded',
        last_result_message_id: null,
        last_duration_ms: null,
      },
      {
        id: 't-running',
        name: 'Running task',
        type: 'recurring',
        schedule: { kind: 'recurring', cron: '*/5 * * * *' },
        session_id: 'real-session',
        content: 'background work',
        enabled: true,
        mode: 'execute',
        last_status: 'running',
      },
    ],
    loading: false,
    error: null,
    load: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    runNow: vi.fn(),
  };
  const hook = (sel?: (s: unknown) => unknown) => (sel ? sel(state) : state);
  return {
    useScheduledTaskStore: Object.assign(hook, { getState: () => state }),
  };
});

const setCurrentSessionId = vi.fn();
vi.mock('../../shared/lib/store', () => ({
  useStore: Object.assign((selector: (s: unknown) => unknown) => selector(sessionState), {
    getState: () => sessionState,
  }),
}));
const sessionState = {
  sessions: [{ id: 'real-session', title: 'Actual conversation' }],
  currentSessionId: 'real-session',
  setCurrentSessionId,
  loadSessions: vi.fn(),
};

import { I18nProvider } from '../../shared/lib/i18n';
import { ScheduledTasks } from '../ScheduledTasks';

function renderPage() {
  return render(
    <MemoryRouter>
      <I18nProvider>
        <ScheduledTasks />
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe('ScheduledTasks — mode badge', () => {
  it('renders mode badges for all tasks', () => {
    renderPage();
    const badges = screen.getAllByTestId('task-mode-badge');
    expect(badges.length).toBe(3);
    expect(badges[0].textContent).toMatch(/自动执行|Auto-execute/i);
    expect(badges[1].textContent).toMatch(/仅提醒|Reminder only/i);
    expect(badges[2].textContent).toMatch(/自动执行|Auto-execute/i);
  });

  it('renders running status badge when last_status=running', () => {
    renderPage();
    const runningBadges = screen.getAllByTestId('task-running-badge');
    expect(runningBadges.length).toBe(1);
    expect(runningBadges[0].textContent).toMatch(/执行中|Executing/i);
  });

  it('renders duration badge when last_duration_ms is a number', () => {
    renderPage();
    const badges = screen.getAllByTestId('task-duration-badge');
    expect(badges.length).toBe(1);
    expect(badges[0].textContent).toMatch(/1234/);
  });
});

describe('ScheduledTasks — view result button', () => {
  it('disables view-result button for deliver-mode task', () => {
    renderPage();
    const cards = screen.getAllByRole('listitem');
    const deliverRow = cards[1];
    const btn = deliverRow.querySelector('[data-testid="view-result-button"]') as HTMLButtonElement;
    expect(btn).toBeTruthy();
    expect(btn.disabled).toBe(true);
  });

  it('calls requestMessageJump on click for execute task with last_result_message_id', () => {
    renderPage();
    const cards = screen.getAllByRole('listitem');
    const executeRow = cards[0];
    const btn = executeRow.querySelector('[data-testid="view-result-button"]') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    fireEvent.click(btn);
    expect(mockRequestMessageJump).toHaveBeenCalledWith({ messageId: 'msg-abc' });
  });

  it('switches to target session before jumping when current differs', async () => {
    sessionState.currentSessionId = 'other-session';
    renderPage();
    const cards = screen.getAllByRole('listitem');
    const executeRow = cards[0];
    const btn = executeRow.querySelector('[data-testid="view-result-button"]') as HTMLButtonElement;
    fireEvent.click(btn);
    await waitFor(() => {
      expect(setCurrentSessionId).toHaveBeenCalledWith('real-session');
      expect(mockRequestMessageJump).toHaveBeenCalledWith({ messageId: 'msg-abc' });
    });
    sessionState.currentSessionId = 'real-session';
  });
});
