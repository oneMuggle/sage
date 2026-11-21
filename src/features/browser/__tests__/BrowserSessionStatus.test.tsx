// @vitest-environment jsdom
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { useStore } from '../../../shared/lib/store';
import { BrowserSessionStatus } from '../BrowserSessionStatus';
import { useBrowserSessionStore } from '../browserSessionStore';

const apiMocks = vi.hoisted(() => ({
  fetchBrowserStatus: vi.fn(),
  updateSessionName: vi.fn(),
}));

vi.mock('../../../shared/api/browserSettingsClient', () => ({
  fetchBrowserStatus: apiMocks.fetchBrowserStatus,
  updateSessionName: apiMocks.updateSessionName,
}));

const toastMocks = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));

vi.mock('sonner', () => ({ toast: { success: toastMocks.success, error: toastMocks.error } }));

interface SessionSeed {
  id: string;
  name: string;
  last_used_at?: string;
}

function makeStatus(
  overrides: Partial<{ active: number; sessions: SessionSeed[] }> = {},
): {
  active: number;
  max: number;
  lruEvict: boolean;
  sessions: Array<{
    id: string;
    name: string;
    last_used_at: string;
    alive: boolean;
    persistent: boolean;
    profile_name: string;
  }>;
} {
  const sessions = (
    overrides.sessions ?? [
      { id: 'sess-one-aaaa', name: '账号A', last_used_at: '2026-11-20T10:00:00Z' },
      { id: 'sess-two-bbbb', name: '' },
    ]
  ).map((session) => ({
    alive: true,
    persistent: true,
    profile_name: '',
    last_used_at: '2026-11-20T10:00:00Z',
    ...session,
  }));
  return {
    active: overrides.active ?? 2,
    max: 4,
    lruEvict: false,
    sessions,
  };
}

function renderStatus(): ReturnType<typeof render> {
  return render(
    <I18nProvider>
      <BrowserSessionStatus />
    </I18nProvider>,
  );
}

async function openPanel(): Promise<void> {
  fireEvent.click(await screen.findByTestId('browser-session-status'));
  expect(screen.getByTestId('browser-session-panel')).toBeTruthy();
}

beforeEach(() => {
  useStore.setState({ currentSessionId: 'conv-1' });
  useBrowserSessionStore.getState().reset();
  apiMocks.fetchBrowserStatus.mockReset();
  apiMocks.updateSessionName.mockReset();
  apiMocks.fetchBrowserStatus.mockResolvedValue(makeStatus());
  apiMocks.updateSessionName.mockResolvedValue({ ok: true, browser_id: 'x', name: 'y' });
  toastMocks.success.mockReset();
  toastMocks.error.mockReset();
});

describe('BrowserSessionStatus', () => {
  it('renders nothing before the first poll resolves', () => {
    apiMocks.fetchBrowserStatus.mockReturnValue(new Promise(() => {}));
    const { container } = renderStatus();
    expect(container.firstChild).toBeNull();
  });

  it('stays hidden while there are no active sessions', async () => {
    apiMocks.fetchBrowserStatus.mockResolvedValue(makeStatus({ active: 0, sessions: [] }));
    renderStatus();
    await waitFor(() => expect(apiMocks.fetchBrowserStatus).toHaveBeenCalled());
    await act(async () => {});
    expect(screen.queryByTestId('browser-session-status')).toBeNull();
  });

  it('swallows poll failures and keeps rendering nothing', async () => {
    apiMocks.fetchBrowserStatus.mockRejectedValue(new Error('401'));
    renderStatus();
    await waitFor(() => expect(apiMocks.fetchBrowserStatus).toHaveBeenCalled());
    await act(async () => {});
    expect(screen.queryByTestId('browser-session-status')).toBeNull();
  });

  it('shows the active/max counter', async () => {
    renderStatus();
    expect(await screen.findByText('2/4')).toBeTruthy();
  });

  it('opens the panel and lists named sessions plus an id fallback', async () => {
    renderStatus();
    await openPanel();
    expect(screen.getByText('账号A')).toBeTruthy();
    expect(screen.getByText('sess-two')).toBeTruthy();
  });

  it('shows the empty hint when the backend reports no sessions', async () => {
    apiMocks.fetchBrowserStatus.mockResolvedValue(makeStatus({ sessions: [] }));
    renderStatus();
    await openPanel();
    expect(screen.getByText('当前没有运行中的浏览器实例')).toBeTruthy();
  });

  it('closes the panel on an outside pointer-down', async () => {
    renderStatus();
    await openPanel();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByTestId('browser-session-panel')).toBeNull();
  });

  it('renames a session and refreshes the snapshot', async () => {
    renderStatus();
    await openPanel();
    fireEvent.click(screen.getAllByLabelText('重命名')[0]);
    const input = screen.getByTestId('browser-session-rename-input-sess-one-aaaa');
    fireEvent.change(input, { target: { value: '账号B' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() =>
      expect(apiMocks.updateSessionName).toHaveBeenCalledWith('sess-one-aaaa', '账号B'),
    );
    expect(toastMocks.success).toHaveBeenCalled();
    await waitFor(() => expect(apiMocks.fetchBrowserStatus).toHaveBeenCalledTimes(2));
  });

  it('does not resend when the name is unchanged', async () => {
    renderStatus();
    await openPanel();
    fireEvent.click(screen.getAllByLabelText('重命名')[0]);
    const input = screen.getByTestId('browser-session-rename-input-sess-one-aaaa');
    fireEvent.change(input, { target: { value: '账号A' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() =>
      expect(screen.queryByTestId('browser-session-rename-input-sess-one-aaaa')).toBeNull(),
    );
    expect(apiMocks.updateSessionName).not.toHaveBeenCalled();
  });

  it('surfaces rename failures through a toast', async () => {
    apiMocks.updateSessionName.mockRejectedValueOnce(new Error('boom'));
    renderStatus();
    await openPanel();
    fireEvent.click(screen.getAllByLabelText('重命名')[0]);
    const input = screen.getByTestId('browser-session-rename-input-sess-one-aaaa');
    fireEvent.change(input, { target: { value: '账号B' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(toastMocks.error).toHaveBeenCalledWith('boom'));
  });

  it('cancels rename on Escape', async () => {
    renderStatus();
    await openPanel();
    fireEvent.click(screen.getAllByLabelText('重命名')[0]);
    const input = screen.getByTestId('browser-session-rename-input-sess-one-aaaa');
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(screen.queryByTestId('browser-session-rename-input-sess-one-aaaa')).toBeNull();
    expect(apiMocks.updateSessionName).not.toHaveBeenCalled();
  });

  it('binds a session to the current conversation and marks it bound', async () => {
    renderStatus();
    await openPanel();
    fireEvent.click(screen.getByTestId('browser-session-bind-sess-one-aaaa'));
    expect(useBrowserSessionStore.getState().byConversation['conv-1']).toBe('sess-one-aaaa');
    await waitFor(() =>
      expect(
        (screen.getByTestId('browser-session-bind-sess-one-aaaa') as HTMLButtonElement).disabled,
      ).toBe(true),
    );
  });

  it('disables binding when no conversation is selected', async () => {
    useStore.setState({ currentSessionId: null });
    renderStatus();
    await openPanel();
    const button = screen.getByTestId('browser-session-bind-sess-one-aaaa') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(useBrowserSessionStore.getState().byConversation).toEqual({});
  });
});
