// ShellStreamDrawer 测试（2026-11-07 Phase 5）
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const listenMock = vi.fn(async () => vi.fn());
vi.mock('../../../shared/api/shellApi', () => ({
  listenShellStream: (...args: unknown[]) => listenMock(...(args as [])),
}));

const invokeMock = vi.fn().mockResolvedValue({ ok: true });
vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));

import { useTaskCenterStore } from '../../../features/task-center/taskCenterStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import { ShellStreamDrawer } from '../ShellStreamDrawer';

function renderDrawer(shellId = 'sh-1') {
  return render(
    <I18nProvider defaultLocale="zh">
      <ShellStreamDrawer shellId={shellId} />
    </I18nProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useTaskCenterStore.setState({ tasks: {}, delivery: null, shellStream: null });
});

describe('ShellStreamDrawer', () => {
  it('shows the command title and terminates a running shell', async () => {
    const store = useTaskCenterStore.getState();
    store.registerShell({ shell_id: 'sh-1', command: 'pytest -q', status: 'running' });
    store.openShellStream('sh-1');

    renderDrawer();
    expect(screen.getByText('pytest -q')).toBeInTheDocument();
    await waitFor(() => expect(listenMock).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId('shell-drawer-terminate'));
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith('shell_kill', { id: 'sh-1' }));
  });

  it('hides the terminate button for an exited shell', () => {
    const store = useTaskCenterStore.getState();
    store.registerShell({
      shell_id: 'sh-2',
      command: 'done-task',
      status: 'exited',
      exit_code: 0,
    });
    renderDrawer('sh-2');
    expect(screen.queryByTestId('shell-drawer-terminate')).toBeNull();
  });

  it('closes via the close button', () => {
    const store = useTaskCenterStore.getState();
    store.registerShell({ shell_id: 'sh-3', command: 'x', status: 'running' });
    store.openShellStream('sh-3');
    renderDrawer('sh-3');

    fireEvent.click(screen.getByTestId('shell-drawer-close'));
    expect(useTaskCenterStore.getState().shellStream).toBeNull();
  });
});
