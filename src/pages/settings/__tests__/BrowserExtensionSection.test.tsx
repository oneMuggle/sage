// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { BrowserExtensionSection } from '../BrowserExtensionSection';

const mocks = vi.hoisted(() => ({
  fetchStatus: vi.fn(),
  createPairingCode: vi.fn(),
  revokeDevice: vi.fn(),
  confirm: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock('../../../shared/api/webAccessClient', () => ({
  fetchBrowserExtensionStatus: mocks.fetchStatus,
  createBrowserExtensionPairingCode: mocks.createPairingCode,
  revokeBrowserExtensionDevice: mocks.revokeDevice,
}));

vi.mock('../../../shared/ui/ConfirmDialog/confirmService', () => ({
  confirmDialog: mocks.confirm,
}));

vi.mock('sonner', () => ({
  toast: { success: mocks.toastSuccess, error: mocks.toastError },
}));

const CONNECTED_STATUS = {
  devices: [
    {
      device_id: 'dev_1',
      label: '我的 Chrome',
      created_at: 1793500000,
      last_seen_at: 1793500100,
      connected: true,
      sharing: true,
    },
  ],
  connected: true,
  shared: {
    device_id: 'dev_1',
    origin: 'https://kns.cnki.net',
    host: 'kns.cnki.net',
    title: '知网首页',
    shared_at: 1793500100,
  },
  base_url: 'http://127.0.0.1:8765',
  extension_dir: '/repo/extension/agent-bridge',
};

const EMPTY_STATUS = {
  devices: [],
  connected: false,
  shared: null,
  base_url: 'http://127.0.0.1:8765',
  extension_dir: null,
};

function renderSection(): void {
  render(
    <I18nProvider>
      <BrowserExtensionSection pollIntervalMs={100000} />
    </I18nProvider>,
  );
}

afterEach(() => {
  vi.clearAllMocks();
});

describe('BrowserExtensionSection', () => {
  it('renders connected device, shared tab and install path', async () => {
    mocks.fetchStatus.mockResolvedValue(CONNECTED_STATUS);
    renderSection();

    await waitFor(() => expect(screen.getByTestId('extension-device-dev_1')).toBeTruthy());
    expect(screen.getByText('我的 Chrome')).toBeTruthy();
    expect(screen.getByText(/知网首页/)).toBeTruthy();
    expect(screen.getByTestId('extension-dir').textContent).toContain(
      '/repo/extension/agent-bridge',
    );
    expect(screen.getByText('在线')).toBeTruthy();
    expect(screen.getByText('正在共享')).toBeTruthy();
  });

  it('shows the empty state and fallback install path', async () => {
    mocks.fetchStatus.mockResolvedValue(EMPTY_STATUS);
    renderSection();

    await waitFor(() => expect(screen.getByTestId('extension-devices-empty')).toBeTruthy());
    expect(screen.getByTestId('extension-dir').textContent).toContain(
      'resources/extension/agent-bridge',
    );
    expect(screen.getByText('扩展未连接')).toBeTruthy();
  });

  it('generates a pairing code with the backend URL', async () => {
    mocks.fetchStatus.mockResolvedValue(EMPTY_STATUS);
    mocks.createPairingCode.mockResolvedValue({
      code: 'ABCDE23456',
      expires_at: Math.floor(Date.now() / 1000) + 600,
      base_url: 'http://127.0.0.1:8834',
      extension_dir: '/repo/extension/agent-bridge',
    });
    renderSection();
    await waitFor(() => expect(screen.getByTestId('extension-generate')).toBeTruthy());

    fireEvent.click(screen.getByTestId('extension-generate'));

    await waitFor(() => expect(screen.getByTestId('extension-pairing-code')).toBeTruthy());
    expect(screen.getByText('ABCDE23456')).toBeTruthy();
    expect(screen.getByText('http://127.0.0.1:8834')).toBeTruthy();
    expect(mocks.createPairingCode).toHaveBeenCalledTimes(1);
  });

  it('hides an expired pairing code', async () => {
    mocks.fetchStatus.mockResolvedValue(EMPTY_STATUS);
    mocks.createPairingCode.mockResolvedValue({
      code: 'ABCDE23456',
      expires_at: 1,
      base_url: 'http://127.0.0.1:8834',
      extension_dir: null,
    });
    renderSection();
    await waitFor(() => expect(screen.getByTestId('extension-generate')).toBeTruthy());

    fireEvent.click(screen.getByTestId('extension-generate'));

    await waitFor(() => expect(screen.getByTestId('extension-pairing-expired')).toBeTruthy());
    expect(screen.queryByText('ABCDE23456')).toBeNull();
  });

  it('revokes a device after confirmation', async () => {
    mocks.fetchStatus.mockResolvedValue(CONNECTED_STATUS);
    mocks.revokeDevice.mockResolvedValue(undefined);
    mocks.confirm.mockResolvedValue(true);
    renderSection();

    await waitFor(() => expect(screen.getByTestId('extension-revoke-dev_1')).toBeTruthy());
    fireEvent.click(screen.getByTestId('extension-revoke-dev_1'));

    await waitFor(() => expect(mocks.revokeDevice).toHaveBeenCalledWith('dev_1'));
    expect(mocks.toastSuccess).toHaveBeenCalled();
  });

  it('does not revoke when the confirmation is cancelled', async () => {
    mocks.fetchStatus.mockResolvedValue(CONNECTED_STATUS);
    mocks.confirm.mockResolvedValue(false);
    renderSection();

    await waitFor(() => expect(screen.getByTestId('extension-revoke-dev_1')).toBeTruthy());
    fireEvent.click(screen.getByTestId('extension-revoke-dev_1'));

    await waitFor(() => expect(mocks.confirm).toHaveBeenCalled());
    expect(mocks.revokeDevice).not.toHaveBeenCalled();
  });

  it('shows a readable error when status cannot be loaded', async () => {
    mocks.fetchStatus.mockRejectedValue(new Error('backend offline'));
    renderSection();

    await waitFor(() => expect(screen.getByTestId('extension-error')).toBeTruthy());
    expect(screen.getByTestId('extension-error').textContent).toContain('backend offline');
  });
});
