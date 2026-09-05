// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { UpdatesTab } from '../UpdatesTab';

const mocks = vi.hoisted(() => ({
  getConfig: vi.fn(),
  setStrategy: vi.fn(),
  setChannel: vi.fn(),
  check: vi.fn(),
}));

const defaultConfig = {
  updateStrategy: 'auto-download' as const,
  channel: 'stable' as const,
  rollbackWindowDays: 7,
  autoRollbackThreshold: 3,
  checkIntervalHours: 24,
  updateServerUrl: 'https://updates.sage.app',
  enableTelemetry: false,
  cacheRetentionDays: 30,
};

function renderTab(): void {
  render(
    <I18nProvider>
      <UpdatesTab />
    </I18nProvider>,
  );
}

beforeEach(() => {
  mocks.getConfig.mockReset().mockResolvedValue(defaultConfig);
  mocks.setStrategy.mockReset().mockResolvedValue(undefined);
  mocks.setChannel.mockReset().mockResolvedValue(undefined);
  mocks.check.mockReset().mockResolvedValue({ updateAvailable: false });
  (window as unknown as { electronAPI?: unknown }).electronAPI = {
    updates: {
      getConfig: mocks.getConfig,
      setStrategy: mocks.setStrategy,
      setChannel: mocks.setChannel,
      check: mocks.check,
    },
  };
});

describe('UpdatesTab', () => {
  it('renders strategy radio group with the expected labels', async () => {
    renderTab();

    await waitFor(() => expect(mocks.getConfig).toHaveBeenCalledOnce());
    expect(screen.getByText('手动更新')).toBeInTheDocument();
    expect(screen.getByText('自动下载，手动安装')).toBeInTheDocument();
    expect(screen.getByText('自动下载安装')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /手动更新/ })).toBeInTheDocument();
  });

  it('renders channel select with all options', async () => {
    renderTab();

    const select = await screen.findByTestId('updates-channel-select');
    await waitFor(() => expect((select as HTMLSelectElement).value).toBe('stable'));
    expect(Array.from((select as HTMLSelectElement).options).map((option) => option.value)).toEqual([
      '',
      'stable',
      'beta',
      'alpha',
    ]);
  });

  it('persists strategy and channel changes', async () => {
    renderTab();

    const manual = await screen.findByRole('radio', { name: /手动更新/ });
    fireEvent.click(manual);
    expect(mocks.setStrategy).toHaveBeenCalledWith('manual');

    const channel = screen.getByTestId('updates-channel-select');
    fireEvent.change(channel, { target: { value: 'beta' } });
    expect(mocks.setChannel).toHaveBeenCalledWith('beta');
  });

  it('checks for updates and shows an available version', async () => {
    mocks.check.mockResolvedValue({ updateAvailable: true, version: '2.0.0' });
    renderTab();

    const button = await screen.findByTestId('updates-check-button');
    fireEvent.click(button);

    expect(mocks.check).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.getByText('发现新版本 2.0.0')).toBeInTheDocument());
  });

  it('shows the up-to-date result', async () => {
    renderTab();

    fireEvent.click(await screen.findByTestId('updates-check-button'));
    await waitFor(() => expect(screen.getByText('当前已是最新版本')).toBeInTheDocument());
  });

  it('disables the check button while checking', async () => {
    let resolveCheck: ((value: { updateAvailable: boolean }) => void) | undefined;
    mocks.check.mockReturnValue(
      new Promise((resolve) => {
        resolveCheck = resolve;
      }),
    );
    renderTab();

    const button = await screen.findByTestId('updates-check-button');
    fireEvent.click(button);
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent('正在检查...');

    resolveCheck?.({ updateAvailable: false });
    await waitFor(() => expect(button).not.toBeDisabled());
  });

  it('shows a translated error when checking fails', async () => {
    mocks.check.mockRejectedValue(new Error('network unavailable'));
    renderTab();

    fireEvent.click(await screen.findByTestId('updates-check-button'));
    await waitFor(() => expect(screen.getByText('检查更新失败，请稍后重试')).toBeInTheDocument());
  });
});
