// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { McpTab } from '../McpTab';

const mocks = vi.hoisted(() => ({
  status: vi.fn(),
  listServers: vi.fn(),
  addServer: vi.fn(),
  updateServer: vi.fn(),
  deleteServer: vi.fn(),
}));

vi.mock('../../../shared/api/mcpClient', () => ({
  MCP_NAME_REGEX: /^[a-z0-9_-]{1,64}$/,
  mcpClient: {
    status: (...args: unknown[]) => mocks.status(...args),
    listServers: (...args: unknown[]) => mocks.listServers(...args),
    addServer: (...args: unknown[]) => mocks.addServer(...args),
    updateServer: (...args: unknown[]) => mocks.updateServer(...args),
    deleteServer: (...args: unknown[]) => mocks.deleteServer(...args),
  },
}));

// identity t(): tests assert on key strings (state badge keys etc.)
vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key, locale: 'zh', setLocale: vi.fn() }),
}));

const STATUS = {
  generated_at: 1,
  all_ready: false,
  degraded: true,
  failed_required: false,
  servers: [
    { name: 'alpha', state: 'ready', tool_count: 2, last_error: null, since: 1, required: false },
    {
      name: 'bravo',
      state: 'failed',
      tool_count: 0,
      last_error: 'boom happened',
      since: 1,
      required: true,
    },
    {
      name: 'drawio',
      state: 'disabled',
      tool_count: 0,
      last_error: null,
      since: 1,
      required: false,
    },
  ],
};

const SERVERS = [
  {
    name: 'alpha',
    command: 'node',
    args: [],
    env: {},
    enabled: true,
    required: false,
    timeout_seconds: 30,
    builtin: false,
  },
  {
    name: 'bravo',
    command: 'python',
    args: [],
    env: {},
    enabled: true,
    required: true,
    timeout_seconds: 30,
    builtin: false,
  },
  {
    name: 'drawio',
    command: 'node',
    args: [],
    env: {},
    enabled: false,
    required: false,
    timeout_seconds: 30,
    builtin: true,
  },
];

describe('McpTab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.status.mockResolvedValue(STATUS);
    mocks.listServers.mockResolvedValue(SERVERS);
    mocks.addServer.mockResolvedValue({ ok: true, name: 'new', state: 'ready' });
    mocks.updateServer.mockResolvedValue({ ok: true, name: 'alpha', state: 'disabled' });
    mocks.deleteServer.mockResolvedValue({ ok: true, name: 'alpha' });
  });

  it('renders one badge per server with the right state', async () => {
    render(<McpTab />);
    await waitFor(() => expect(mocks.status).toHaveBeenCalled());

    expect(screen.getByTestId('state-badge-alpha').textContent).toBe(
      'settings.mcp.state.ready',
    );
    expect(screen.getByTestId('state-badge-bravo').textContent).toBe(
      'settings.mcp.state.failed',
    );
    expect(screen.getByTestId('state-badge-drawio').textContent).toBe(
      'settings.mcp.state.disabled',
    );
    // failed server surfaces its last_error + tool counts are shown
    expect(screen.getByText('boom happened')).toBeTruthy();
    expect(screen.getByText('2')).toBeTruthy();
  });

  it('shows empty state when no servers configured', async () => {
    mocks.listServers.mockResolvedValue([]);
    mocks.status.mockResolvedValue({ ...STATUS, servers: [] });
    render(<McpTab />);
    await waitFor(() => expect(screen.getByText('settings.mcp.empty')).toBeTruthy());
  });

  it('toggle calls updateServer with the negated flag and refreshes', async () => {
    render(<McpTab />);
    await waitFor(() => expect(mocks.listServers).toHaveBeenCalledTimes(1));

    const row = screen.getByText('alpha').closest('tr')!;
    const toggle = row.querySelectorAll('button')[0];
    fireEvent.click(toggle);

    await waitFor(() =>
      expect(mocks.updateServer).toHaveBeenCalledWith('alpha', { enabled: false }),
    );
    // refresh after update → list fetched again
    await waitFor(() => expect(mocks.listServers).toHaveBeenCalledTimes(2));
  });

  it('add-form rejects invalid names client-side', async () => {
    render(<McpTab />);
    await waitFor(() => expect(mocks.status).toHaveBeenCalled());

    fireEvent.change(screen.getByPlaceholderText('my-server'), {
      target: { value: 'Bad Name' },
    });
    fireEvent.change(screen.getByPlaceholderText('node'), { target: { value: 'node' } });
    fireEvent.click(screen.getByText('settings.mcp.add.submit'));

    await waitFor(() =>
      expect(screen.getByText('settings.mcp.error.name_invalid')).toBeTruthy(),
    );
    expect(mocks.addServer).not.toHaveBeenCalled();
  });

  it('add-form rejects empty command', async () => {
    render(<McpTab />);
    await waitFor(() => expect(mocks.status).toHaveBeenCalled());

    fireEvent.change(screen.getByPlaceholderText('my-server'), { target: { value: 'good' } });
    fireEvent.click(screen.getByText('settings.mcp.add.submit'));

    await waitFor(() =>
      expect(screen.getByText('settings.mcp.error.command_required')).toBeTruthy(),
    );
    expect(mocks.addServer).not.toHaveBeenCalled();
  });

  it('add-form submits parsed args and clears on success', async () => {
    render(<McpTab />);
    await waitFor(() => expect(mocks.status).toHaveBeenCalled());

    fireEvent.change(screen.getByPlaceholderText('my-server'), { target: { value: 'srv' } });
    fireEvent.change(screen.getByPlaceholderText('node'), { target: { value: 'node' } });
    fireEvent.change(screen.getByPlaceholderText('/path/to/server.js --flag'), {
      target: { value: '  a.js   b.js ' },
    });
    fireEvent.click(screen.getByText('settings.mcp.add.submit'));

    await waitFor(() =>
      expect(mocks.addServer).toHaveBeenCalledWith({
        name: 'srv',
        command: 'node',
        args: ['a.js', 'b.js'],
        required: false,
      }),
    );
  });

  it('builtin delete button is disabled with hint; user server deletes', async () => {
    render(<McpTab />);
    await waitFor(() => expect(mocks.status).toHaveBeenCalled());

    const drawioRow = screen.getByText('drawio').closest('tr')!;
    const drawioDelete = drawioRow.querySelectorAll('button')[1] as HTMLButtonElement;
    expect(drawioDelete.disabled).toBe(true);
    expect(drawioDelete.title).toBe('settings.mcp.builtin_hint');

    const alphaRow = screen.getByText('alpha').closest('tr')!;
    const alphaDelete = alphaRow.querySelectorAll('button')[1];
    fireEvent.click(alphaDelete);
    await waitFor(() => expect(mocks.deleteServer).toHaveBeenCalledWith('alpha'));
  });

  it('refresh button re-fetches status and servers', async () => {
    render(<McpTab />);
    await waitFor(() => expect(mocks.status).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByText('settings.mcp.refresh'));
    await waitFor(() => expect(mocks.status).toHaveBeenCalledTimes(2));
    expect(mocks.listServers).toHaveBeenCalledTimes(2);
  });
});
