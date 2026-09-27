// @vitest-environment jsdom
/**
 * RemoteWorkspacesTab（Workspace MCP Server M4）契约：
 * - 后端状态走 remoteMcpApi；隧道 / 急停 / 复制走 electronAPI.remoteMcp
 * - 开启命令权限需二次确认；取消则不发请求
 * - 急停按钮调用主进程 emergencyStop
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { RemoteWorkspacesTab } from '../RemoteWorkspacesTab';

const mocks = vi.hoisted(() => ({
  state: vi.fn(),
  updateWorkspace: vi.fn(),
  startListener: vi.fn(),
  bridge: null as null | Record<string, ReturnType<typeof vi.fn>>,
}));

vi.mock('../../../shared/api/remoteMcpApi', () => ({
  DEFAULT_REMOTE_MCP_PORT: 8767,
  remoteMcpApi: {
    state: (...a: unknown[]) => mocks.state(...a),
    updateWorkspace: (...a: unknown[]) => mocks.updateWorkspace(...a),
    startListener: (...a: unknown[]) => mocks.startListener(...a),
    stopListener: vi.fn(),
    createWorkspace: vi.fn(),
    rotateWorkspace: vi.fn(),
    deleteWorkspace: vi.fn(),
    resume: vi.fn(),
  },
  remoteMcpBridge: () => mocks.bridge,
}));

const STATE = {
  listener: { running: true, port: 8767, error: null, host: '127.0.0.1' },
  paused: false,
  running_commands: 0,
  workspaces: [
    { id: 'ws1', name: 'sage', root: 'E:/sage', enabled: true, permissions: { read: true }, sessions: 2 },
  ],
  audit: [{ time: '2026-09-26T00:00:00Z', event: 'tool.call', tool: 'read_file', code: 'ok' }],
};

const TUNNEL = {
  state: 'stopped',
  url: null,
  error: null,
  health: { state: 'stopped' },
  addressChanged: false,
  retryCount: 0,
  supported: true,
  hotkeyRegistered: true,
};

function renderTab(): void {
  render(
    <I18nProvider>
      <RemoteWorkspacesTab />
    </I18nProvider>,
  );
}

beforeEach(() => {
  mocks.state.mockResolvedValue(STATE);
  mocks.updateWorkspace.mockResolvedValue(STATE);
  mocks.bridge = {
    tunnelState: vi.fn().mockResolvedValue(TUNNEL),
    startTunnel: vi.fn().mockResolvedValue(TUNNEL),
    stopTunnel: vi.fn().mockResolvedValue(TUNNEL),
    emergencyStop: vi.fn().mockResolvedValue(TUNNEL),
    copyUrl: vi.fn().mockResolvedValue(true),
  };
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('RemoteWorkspacesTab', () => {
  it('renders workspaces and audit from backend state', async () => {
    renderTab();
    expect(await screen.findByTestId('remote-ws-ws1')).toBeTruthy();
    expect(screen.getByText('E:/sage')).toBeTruthy();
    expect(screen.getByText('read_file')).toBeTruthy();
  });

  it('asks for confirmation before enabling shell; cancel sends nothing', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderTab();
    fireEvent.click(await screen.findByTestId('remote-ws-perm-shell-ws1'));
    expect(confirm).toHaveBeenCalled();
    expect(mocks.updateWorkspace).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByTestId('remote-ws-perm-shell-ws1'));
    await waitFor(() =>
      expect(mocks.updateWorkspace).toHaveBeenCalledWith('ws1', { permissions: { shell: true } }),
    );
  });

  it('revoking read does not require confirmation', async () => {
    const confirm = vi.spyOn(window, 'confirm');
    renderTab();
    fireEvent.click(await screen.findByTestId('remote-ws-perm-read-ws1'));
    await waitFor(() =>
      expect(mocks.updateWorkspace).toHaveBeenCalledWith('ws1', { permissions: { read: false } }),
    );
    expect(confirm).not.toHaveBeenCalled();
  });

  it('emergency stop goes through the main-process bridge', async () => {
    renderTab();
    fireEvent.click(await screen.findByTestId('remote-mcp-emergency'));
    await waitFor(() => expect(mocks.bridge!.emergencyStop).toHaveBeenCalled());
    expect(await screen.findByTestId('remote-mcp-notice')).toBeTruthy();
  });

  it('shows backend errors inline', async () => {
    mocks.state.mockRejectedValue(new Error('backend down'));
    renderTab();
    expect((await screen.findByTestId('remote-mcp-error')).textContent).toContain('backend down');
  });
});
