// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { BrowserPanel } from '../BrowserPanel';

const panel = {
  show: vi.fn(async () => ({ ok: true })),
  hide: vi.fn(async () => ({ ok: true })),
  setBounds: vi.fn(async () => ({ ok: true })),
  navigate: vi.fn(async () => ({ ok: true })),
  back: vi.fn(async () => ({ ok: true })),
  forward: vi.fn(async () => ({ ok: true })),
  reload: vi.fn(async () => ({ ok: true })),
  current: vi.fn(async () => ({
    url: 'https://kns.cnki.net/',
    title: '知网',
    canGoBack: true,
    canGoForward: false,
  })),
};

class ResizeObserverStub {
  observe = vi.fn();
  disconnect = vi.fn();
}

function installElectronApi(value: typeof panel | undefined): void {
  (window as unknown as { electronAPI?: unknown }).electronAPI =
    value === undefined ? undefined : { browserPanel: value };
}

function renderPanel(): ReturnType<typeof render> {
  return render(
    <I18nProvider>
      <BrowserPanel />
    </I18nProvider>,
  );
}

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', ResizeObserverStub);
  Object.values(panel).forEach((fn) => fn.mockClear());
  panel.current.mockImplementation(async () => ({
    url: 'https://kns.cnki.net/',
    title: '知网',
    canGoBack: true,
    canGoForward: false,
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
  installElectronApi(undefined);
});

describe('BrowserPanel', () => {
  it('shows the desktop-only hint without the Electron API', () => {
    installElectronApi(undefined);
    renderPanel();
    expect(screen.getByText(/仅在 Sage 桌面端可用/)).toBeTruthy();
  });

  it('shows the BrowserView on mount, reports bounds and hides on unmount', async () => {
    installElectronApi(panel);
    const { unmount } = renderPanel();
    await waitFor(() => expect(panel.show).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(panel.setBounds).toHaveBeenCalled());
    expect((panel.setBounds.mock.calls[0] as unknown[])[0]).toMatchObject({
      x: 0,
      y: 0,
      width: 0,
      height: 0,
    });
    unmount();
    expect(panel.hide).toHaveBeenCalled();
  });

  it('navigates only for http(s) URLs', async () => {
    installElectronApi(panel);
    renderPanel();
    const input = screen.getByTestId('browser-panel-address');
    fireEvent.change(input, { target: { value: 'file:///etc/passwd' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(panel.navigate).not.toHaveBeenCalled();
    expect(screen.getByText(/http:\/\//)).toBeTruthy();

    fireEvent.change(input, { target: { value: 'https://kns.cnki.net/' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() =>
      expect(panel.navigate).toHaveBeenCalledWith('https://kns.cnki.net/'),
    );
  });

  it('reflects current URL and navigation buttons', async () => {
    installElectronApi(panel);
    renderPanel();
    await waitFor(() =>
      expect((screen.getByTestId('browser-panel-address') as HTMLInputElement).value).toBe(
        'https://kns.cnki.net/',
      ),
    );
    expect((screen.getByLabelText('后退') as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByLabelText('前进') as HTMLButtonElement).disabled).toBe(true);
  });
});
