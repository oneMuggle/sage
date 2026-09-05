// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { UpdateStateChangedEvent } from '../../../electron/updateIpc';
import { I18nProvider } from '../../shared/lib/i18n';
import { UpdateDialog } from '../UpdateDialog';

const mocks = vi.hoisted(() => ({
  download: vi.fn(),
  install: vi.fn(),
  rollback: vi.fn(),
  canRollback: vi.fn(),
  onStateChanged: vi.fn(),
}));

type StatePayload = Extract<UpdateStateChangedEvent, { type: 'state' }>['state'];

const updateState = (overrides: Partial<StatePayload> = {}) => ({
  currentVersion: '1.0.0',
  lastKnownGoodVersion: '1.0.0',
  lastKnownGoodInstallDate: '2026-09-05T12:00:00.000Z',
  crashCount: 0,
  rollbackWindowDays: 7,
  updateStrategy: 'manual' as const,
  lastCheckTime: '2026-09-05T12:00:00.000Z',
  updateAvailable: true,
  availableUpdate: null,
  pendingUpdate: null,
  lastRecordedVersion: '1.0.0',
  ...overrides,
});

let stateHandler: ((event: UpdateStateChangedEvent) => void) | undefined;

function renderDialog(): void {
  render(
    <I18nProvider>
      <UpdateDialog />
    </I18nProvider>,
  );
}

beforeEach(() => {
  stateHandler = undefined;
  mocks.download.mockReset().mockResolvedValue(undefined);
  mocks.install.mockReset().mockResolvedValue(undefined);
  mocks.rollback.mockReset().mockResolvedValue(undefined);
  mocks.canRollback.mockReset().mockResolvedValue({ allowed: false });
  mocks.onStateChanged
    .mockReset()
    .mockImplementation((handler: (event: UpdateStateChangedEvent) => void) => {
      stateHandler = handler;
      return () => {
        stateHandler = undefined;
      };
    });
  (window as unknown as { electronAPI?: unknown }).electronAPI = {
    updates: {
      download: mocks.download,
      install: mocks.install,
      rollback: mocks.rollback,
      canRollback: mocks.canRollback,
      onStateChanged: mocks.onStateChanged,
    },
  };
});

describe('UpdateDialog', () => {
  it('renders nothing when no update is available', async () => {
    renderDialog();
    stateHandler?.({ type: 'state', state: updateState({ updateAvailable: false }) });
    await waitFor(() => expect(screen.queryByTestId('update-dialog')).not.toBeInTheDocument());
  });

  it('shows the new version and release notes', async () => {
    renderDialog();
    stateHandler?.({
      type: 'state',
      state: updateState({
        pendingUpdate: {
          version: '1.2.0',
          downloadedAt: '2026-09-05T12:00:00.000Z',
          releaseNotes: '修复已知问题\n新增功能',
        },
        updateAvailable: false,
      }),
    });
    expect(await screen.findByText('更新已就绪，重启后生效')).toBeInTheDocument();
    expect(screen.getByText(/版本 1\.2\.0 已下载完成/)).toBeInTheDocument();
  });

  it('shows release notes or the empty placeholder for an available update', async () => {
    renderDialog();
    stateHandler?.({
      type: 'state',
      state: updateState({
        updateAvailable: true,
        availableUpdate: {
          version: '1.2.0',
          releaseNotes: undefined,
        },
        pendingUpdate: null,
      }),
    });
    expect(await screen.findByText(/发现新版本/)).toHaveTextContent('发现新版本');
    expect(screen.getByText('无发布说明')).toBeInTheDocument();
  });

  it('downloads an available update', async () => {
    renderDialog();
    stateHandler?.({ type: 'state', state: updateState() });
    fireEvent.click(await screen.findByRole('button', { name: '立即下载' }));
    expect(mocks.download).toHaveBeenCalledOnce();
  });

  it('shows download progress and percentage', async () => {
    renderDialog();
    stateHandler?.({ type: 'state', state: updateState() });
    stateHandler?.({ type: 'progress', percent: 42.4 });
    expect(await screen.findByRole('progressbar')).toHaveAttribute('aria-valuenow', '42');
    expect(screen.getByTestId('update-dialog-percent')).toHaveTextContent('42%');
  });

  it('installs a downloaded update', async () => {
    renderDialog();
    stateHandler?.({
      type: 'state',
      state: updateState({
        updateAvailable: false,
        pendingUpdate: { version: '1.2.0', downloadedAt: '2026-09-05T12:00:00.000Z' },
      }),
    });
    fireEvent.click(await screen.findByRole('button', { name: '立即安装' }));
    expect(mocks.install).toHaveBeenCalledOnce();
  });

  it('defers the dialog', async () => {
    renderDialog();
    stateHandler?.({ type: 'state', state: updateState() });
    fireEvent.click(await screen.findByRole('button', { name: '稍后提醒' }));
    expect(screen.queryByTestId('update-dialog')).not.toBeInTheDocument();
  });

  it('confirms rollback and calls rollback when allowed', async () => {
    mocks.canRollback.mockResolvedValue({ allowed: true });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderDialog();
    stateHandler?.({ type: 'state', state: updateState() });
    const rollbackButton = await screen.findByRole('button', { name: '回退到上一版本' });
    fireEvent.click(rollbackButton);
    expect(window.confirm).toHaveBeenCalledOnce();
    expect(mocks.rollback).toHaveBeenCalledWith('manual');
    vi.restoreAllMocks();
  });

  it('hides rollback when it is not allowed', async () => {
    renderDialog();
    stateHandler?.({ type: 'state', state: updateState() });
    await screen.findByTestId('update-dialog');
    expect(screen.queryByRole('button', { name: '回退到上一版本' })).not.toBeInTheDocument();
  });

  it('unsubscribes from state events on unmount', () => {
    const { unmount } = render(
      <I18nProvider>
        <UpdateDialog />
      </I18nProvider>,
    );
    expect(mocks.onStateChanged).toHaveBeenCalledOnce();
    unmount();
    expect(stateHandler).toBeUndefined();
  });
});
