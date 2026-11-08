// TaskCenterWidget 后台 shell 聚合测试（2026-11-07 Phase 5）
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const listShellsMock = vi.fn();
vi.mock('../../../shared/api/shellApi', () => ({
  listShells: (...args: unknown[]) => listShellsMock(...(args as [])),
  listenShellStream: vi.fn(async () => vi.fn()),
}));

import { useLaneBoardStore } from '../../../entities/orchestration/laneBoardStore';
import { useChatStreamStore } from '../../../features/send-message/chatStreamStore';
import { useTaskCenterStore } from '../../../features/task-center/taskCenterStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import { useStore } from '../../../shared/lib/store';
import { TaskCenterWidget } from '../TaskCenterWidget';

function renderWidget() {
  return render(
    <MemoryRouter initialEntries={['/chat']}>
      <I18nProvider>
        <TaskCenterWidget />
      </I18nProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  listShellsMock.mockResolvedValue([]);
  useTaskCenterStore.setState({ tasks: {}, delivery: null, shellStream: null });
  useLaneBoardStore.setState({ lanes: [], loading: false, error: null, teamIdFilter: null });
  useChatStreamStore.setState({ sessions: {} });
  useStore.setState({ sessions: [], currentSessionId: null, messages: [], isLoading: false });
});

describe('TaskCenterWidget 后台 shell 聚合 (Phase 5)', () => {
  it('polls background shells into the capsule and opens the drawer on click', async () => {
    listShellsMock.mockResolvedValue([
      {
        shell_id: 'sh-1',
        command: 'pytest -q',
        status: 'running',
        pid: 4242,
        age_seconds: 5,
        exit_code: null,
      },
    ]);
    renderWidget();

    await waitFor(() => expect(screen.getByTestId('task-center-toggle')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('task-center-toggle'));

    await waitFor(() => expect(screen.getByText('pytest -q')).toBeInTheDocument());
    fireEvent.click(screen.getByText('pytest -q'));

    await waitFor(() => expect(screen.getByTestId('shell-stream-drawer')).toBeInTheDocument());
    expect(useTaskCenterStore.getState().shellStream).toBe('sh-1');
  });

  it('renders nothing when no tasks or shells exist', async () => {
    renderWidget();
    await waitFor(() => expect(listShellsMock).toHaveBeenCalled());
    expect(screen.queryByTestId('task-center-toggle')).toBeNull();
  });
});
